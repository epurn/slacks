#!/usr/bin/env node
// Guard script: forbid `colors.accent` (or any `<x>.accent`) as a text `color:`
// value in the mobile source tree.
//
// `accent` fails WCAG AA as text on the light surface (prior-audit C-UX-1);
// `accentText` is the AA-verified token for that use (see theme/theme.test.ts).
// Background/border/fill/stroke uses of `accent` are unaffected — only the
// object property literally named `color` is checked.
//
// This is a standalone verify-hook script (run from mobile/verify.sh), NOT an
// ESLint rule: the guard parses each source file with the TypeScript compiler
// and walks the value side of every `color:` property looking for a `.accent`
// member-access leaf (including inside a ternary / `&&` / `||` / `??`).
//
// Baseline-aware: `accent-text-baseline.json` pins a per-file COUNT of
// pre-existing violations so the guard can be adopted without a flag-day
// rewrite. Each file's first N accent-as-text sites (in source order) are
// exempt, where N is that file's baseline count; anything beyond N — including
// a brand-new file with no baseline entry — fails. Per-screen stories drain
// their file's count to 0 (and delete the entry) as they swap to `accentText`.
//
// Usage:
//   node scripts/check-accent-as-text.js          # verify; exit 1 on new sites
//   node scripts/check-accent-as-text.js --list    # print the live per-file counts
"use strict";

const fs = require("fs");
const path = require("path");
const ts = require("typescript");

const MOBILE_ROOT = path.resolve(__dirname, "..");
const DEFAULT_BASELINE_PATH = path.join(MOBILE_ROOT, "accent-text-baseline.json");

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

// Walks the value side of a `color: <expr>` property looking for a leaf
// member access ending in `.accent` (e.g. `colors.accent`, but not
// `colors.accentText` / `colors.accentForeground`). Unwraps parentheses and
// descends into ternary / logical / nullish branches.
function referencesAccentAsText(node) {
  if (!node) return false;
  if (ts.isParenthesizedExpression(node)) {
    return referencesAccentAsText(node.expression);
  }
  if (ts.isConditionalExpression(node)) {
    return referencesAccentAsText(node.whenTrue) || referencesAccentAsText(node.whenFalse);
  }
  if (ts.isBinaryExpression(node)) {
    const op = node.operatorToken.kind;
    if (
      op === ts.SyntaxKind.AmpersandAmpersandToken ||
      op === ts.SyntaxKind.BarBarToken ||
      op === ts.SyntaxKind.QuestionQuestionToken
    ) {
      return referencesAccentAsText(node.left) || referencesAccentAsText(node.right);
    }
    return false;
  }
  if (ts.isPropertyAccessExpression(node)) {
    return node.name.kind === ts.SyntaxKind.Identifier && node.name.text === "accent";
  }
  return false;
}

// True when the property key is literally `color` (identifier or string key),
// not a computed key and not `backgroundColor` / `borderColor` / etc.
function nameIsColor(name) {
  if (ts.isIdentifier(name)) return name.text === "color";
  if (ts.isStringLiteral(name)) return name.text === "color";
  return false;
}

// Scan a single source string; returns the 1-based line numbers of every
// accent-as-text `color:` site, in source order.
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
      nameIsColor(node.name) &&
      referencesAccentAsText(node.initializer)
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

// { rel -> count } of every accent-as-text site in the live tree (for --list /
// baseline regeneration).
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
      "✖ accent-as-text guard: colors.accent used as a text color beyond the tracked baseline.",
    );
    console.error(
      "  accent fails WCAG AA as text on the light surface — use colors.accentText instead.",
    );
    console.error(
      "  (backgroundColor / borderColor / fill / stroke uses of colors.accent are fine.)",
    );
    for (const f of failures) {
      console.error(`  ${f.file}: new accent-as-text site(s) at line(s) ${f.lines.join(", ")}`);
    }
    console.error(
      "  If a new pre-existing site is intentional, bump its count in accent-text-baseline.json.",
    );
    process.exitCode = 1;
    return;
  }

  console.log("✓ accent-as-text guard: no colors.accent-as-text sites beyond the baseline.");
}

if (require.main === module) {
  main(process.argv.slice(2));
}

module.exports = {
  MOBILE_ROOT,
  DEFAULT_BASELINE_PATH,
  referencesAccentAsText,
  scanSource,
  evaluate,
  loadBaselineCounts,
  collectFiles,
  scanTree,
};
