#!/usr/bin/env node
// Guard script: forbid a numeric `fontSize: N` literal in the mobile source
// tree — every fontSize must reference the `typeScale` token set instead
// (theme/typography.ts), so a future type-scale change updates every surface.
//
// This is a standalone verify-hook script (run from mobile/verify.sh), NOT an
// ESLint rule: the guard parses each source file with the TypeScript compiler
// and walks the value side of every `fontSize:` property looking for a
// numeric-literal leaf (including inside a ternary / `&&` / `||` / `??`).
//
// Baseline-aware: `font-size-baseline.json` pins a per-file COUNT of
// pre-existing numeric fontSize sites (FTY-192) so the guard can be adopted
// without a flag-day rewrite. Each file's first N sites (in source order) are
// exempt, where N is that file's baseline count; anything beyond N —
// including a brand-new file with no baseline entry — fails. Per-screen
// stories (FTY-213-217) drain their file's count to 0 (and delete the entry)
// as they route the literal through typeScale; the guard is fully strict once
// this list is empty.
//
// Usage:
//   node scripts/check-font-size-literal.js          # verify; exit 1 on new sites
//   node scripts/check-font-size-literal.js --list    # print the live per-file counts
"use strict";

const fs = require("fs");
const path = require("path");
const ts = require("typescript");

const MOBILE_ROOT = path.resolve(__dirname, "..");
const DEFAULT_BASELINE_PATH = path.join(MOBILE_ROOT, "font-size-baseline.json");

// Directories that never hold shipping UI style objects; skipping them keeps the
// guard fast and avoids test fixtures / build output tripping it.
const IGNORED_DIRS = new Set([
  "node_modules",
  ".expo",
  ".git",
  "dist",
  "coverage",
  "android",
  "ios",
  "scripts",
  "eslint-rules",
  "e2e",
  "__tests__",
  "__mocks__",
  "testUtils",
  ".maestro",
]);

const SOURCE_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx"]);

function isScannableFile(name) {
  if (name.endsWith(".d.ts")) return false;
  if (/\.(test|spec)\.[jt]sx?$/.test(name)) return false;
  return SOURCE_EXTENSIONS.has(path.extname(name));
}

function scriptKindFor(fileName) {
  if (fileName.endsWith(".tsx")) return ts.ScriptKind.TSX;
  if (fileName.endsWith(".ts")) return ts.ScriptKind.TS;
  if (fileName.endsWith(".jsx")) return ts.ScriptKind.JSX;
  return ts.ScriptKind.JS;
}

// Walks the value side of a `fontSize: <expr>` property looking for a leaf
// numeric literal (e.g. `fontSize: 20`, but not `fontSize: typeScale.body`).
// Unwraps parentheses and descends into ternary / logical / nullish branches.
function referencesNumericFontSize(node) {
  if (!node) return false;
  if (ts.isParenthesizedExpression(node)) {
    return referencesNumericFontSize(node.expression);
  }
  if (ts.isConditionalExpression(node)) {
    return referencesNumericFontSize(node.whenTrue) || referencesNumericFontSize(node.whenFalse);
  }
  if (ts.isBinaryExpression(node)) {
    const op = node.operatorToken.kind;
    if (
      op === ts.SyntaxKind.AmpersandAmpersandToken ||
      op === ts.SyntaxKind.BarBarToken ||
      op === ts.SyntaxKind.QuestionQuestionToken
    ) {
      return referencesNumericFontSize(node.left) || referencesNumericFontSize(node.right);
    }
    return false;
  }
  return ts.isNumericLiteral(node);
}

// True when the property key is literally `fontSize` (identifier or string
// key), not a computed key.
function nameIsFontSize(name) {
  if (ts.isIdentifier(name)) return name.text === "fontSize";
  if (ts.isStringLiteral(name)) return name.text === "fontSize";
  return false;
}

// Scan a single source string; returns the 1-based line numbers of every
// numeric-fontSize site, in source order.
function scanSource(code, fileName) {
  const name = fileName || "virtual.tsx";
  const sourceFile = ts.createSourceFile(
    name,
    code,
    ts.ScriptTarget.Latest,
    /* setParentNodes */ true,
    scriptKindFor(name),
  );
  const positions = [];
  function visit(node) {
    if (
      ts.isPropertyAssignment(node) &&
      nameIsFontSize(node.name) &&
      referencesNumericFontSize(node.initializer)
    ) {
      positions.push(node.getStart(sourceFile));
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  positions.sort((a, b) => a - b);
  return positions.map((pos) => sourceFile.getLineAndCharacterOfPosition(pos).line + 1);
}

function loadBaselineCounts(baselinePath) {
  const data = JSON.parse(fs.readFileSync(baselinePath, "utf8"));
  const counts = new Map();
  for (const site of data.sites) {
    counts.set(site.file, site.count);
  }
  return counts;
}

// Given a file's relative path + source and the baseline map, return the line
// numbers of the sites that EXCEED the file's baselined count (i.e. new debt).
function evaluate(relFile, code, baselineCounts) {
  const lines = scanSource(code, relFile);
  const allowed = baselineCounts.get(relFile) ?? 0;
  return lines.slice(allowed);
}

function collectFiles(root) {
  const out = [];
  function walk(dir) {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      if (entry.isDirectory()) {
        if (IGNORED_DIRS.has(entry.name)) continue;
        walk(path.join(dir, entry.name));
      } else if (entry.isFile() && isScannableFile(entry.name)) {
        out.push(path.join(dir, entry.name));
      }
    }
  }
  walk(root);
  out.sort();
  return out;
}

function relOf(abs) {
  return path.relative(MOBILE_ROOT, abs).split(path.sep).join("/");
}

// { rel -> count } of every numeric-fontSize site in the live tree (for
// --list / baseline regeneration).
function scanTree(root) {
  const counts = {};
  for (const abs of collectFiles(root)) {
    const lines = scanSource(fs.readFileSync(abs, "utf8"), relOf(abs));
    if (lines.length) counts[relOf(abs)] = lines.length;
  }
  return counts;
}

function main(argv) {
  if (argv.includes("--list")) {
    const counts = scanTree(MOBILE_ROOT);
    console.log(JSON.stringify(counts, null, 2));
    return;
  }

  const baselineCounts = loadBaselineCounts(DEFAULT_BASELINE_PATH);
  const failures = [];
  for (const abs of collectFiles(MOBILE_ROOT)) {
    const rel = relOf(abs);
    const extra = evaluate(rel, fs.readFileSync(abs, "utf8"), baselineCounts);
    if (extra.length) failures.push({ file: rel, lines: extra });
  }

  if (failures.length) {
    console.error(
      "✖ fontSize guard: numeric fontSize literal used beyond the tracked baseline.",
    );
    console.error(
      "  Reference a theme/typography.ts typeScale token instead (e.g. typeScale.body).",
    );
    for (const f of failures) {
      console.error(`  ${f.file}: new numeric fontSize site(s) at line(s) ${f.lines.join(", ")}`);
    }
    console.error(
      "  If a new pre-existing site is intentional, bump its count in font-size-baseline.json.",
    );
    process.exitCode = 1;
    return;
  }

  console.log("✓ fontSize guard: no numeric fontSize sites beyond the baseline.");
}

if (require.main === module) {
  main(process.argv.slice(2));
}

module.exports = {
  MOBILE_ROOT,
  DEFAULT_BASELINE_PATH,
  referencesNumericFontSize,
  scanSource,
  evaluate,
  loadBaselineCounts,
  collectFiles,
  scanTree,
};
