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
// Baseline-aware and SITE-BASED: `font-size-baseline.json` pins each
// pre-existing numeric fontSize site (FTY-192) by its enclosing style-key
// context (e.g. `styles.axisLabel`) plus its numeric value(s), so the guard
// can be adopted without a flag-day rewrite. Sites are matched per file as a
// multiset of `context@sizes` keys: a scanned site is exempt only if the
// file's baseline still has an unconsumed entry with the same context and
// value. Any NEW literal — a new style key, a changed value, a duplicate of
// an existing site, or any site in an unlisted file — fails. Per-screen
// stories (FTY-213-217) delete a file's site entries (and then the file
// entry) as they route each literal through typeScale; the guard is fully
// strict once this list is empty.
//
// Usage:
//   node scripts/check-font-size-literal.js          # verify; exit 1 on new sites
//   node scripts/check-font-size-literal.js --list    # print the live per-file sites
"use strict";

const fs = require("fs");
const path = require("path");
const ts = require("typescript");
const { contextOf, siteKey: sharedSiteKey } = require("./site-identity");

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

// Collects every leaf numeric literal reachable from a `fontSize: <expr>`
// value (e.g. `fontSize: 20`, both arms of `selected ? 20 : 16`, the operands
// of `&&` / `||` / `??`) — but not token references like `typeScale.body`.
// Returns the values found, [] when the expression holds no numeric literal.
function collectNumericFontSizes(node, out = []) {
  if (!node) return out;
  if (ts.isParenthesizedExpression(node)) {
    return collectNumericFontSizes(node.expression, out);
  }
  if (ts.isConditionalExpression(node)) {
    collectNumericFontSizes(node.whenTrue, out);
    collectNumericFontSizes(node.whenFalse, out);
    return out;
  }
  if (ts.isBinaryExpression(node)) {
    const op = node.operatorToken.kind;
    if (
      op === ts.SyntaxKind.AmpersandAmpersandToken ||
      op === ts.SyntaxKind.BarBarToken ||
      op === ts.SyntaxKind.QuestionQuestionToken
    ) {
      collectNumericFontSizes(node.left, out);
      collectNumericFontSizes(node.right, out);
    }
    return out;
  }
  if (ts.isNumericLiteral(node)) out.push(Number(node.text));
  return out;
}

// True when the property key is literally `fontSize` (identifier or string
// key), not a computed key.
function nameIsFontSize(name) {
  if (ts.isIdentifier(name)) return name.text === "fontSize";
  if (ts.isStringLiteral(name)) return name.text === "fontSize";
  return false;
}

// A stable multiset key for one site: enclosing context + sorted values.
// contextOf (the enclosing style-key chain) is shared with
// check-accent-as-text.js via ./site-identity.
function siteKey(site) {
  return sharedSiteKey(site.context, [...site.sizes].sort((a, b) => a - b));
}

// Scan a single source string; returns every numeric-fontSize site, in source
// order, as { line, context, sizes }.
function scanSource(code, fileName) {
  const name = fileName || "virtual.tsx";
  const sourceFile = ts.createSourceFile(
    name,
    code,
    ts.ScriptTarget.Latest,
    /* setParentNodes */ true,
    scriptKindFor(name),
  );
  const sites = [];
  function visit(node) {
    if (ts.isPropertyAssignment(node) && nameIsFontSize(node.name)) {
      const sizes = collectNumericFontSizes(node.initializer);
      if (sizes.length) {
        sites.push({
          pos: node.getStart(sourceFile),
          line: sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1,
          context: contextOf(node),
          sizes,
        });
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  sites.sort((a, b) => a.pos - b.pos);
  return sites.map(({ line, context, sizes }) => ({ line, context, sizes }));
}

// { relFile -> Map<siteKey, count> } from the committed baseline.
function loadBaselineSites(baselinePath) {
  const data = JSON.parse(fs.readFileSync(baselinePath, "utf8"));
  const byFile = new Map();
  for (const entry of data.files) {
    const keys = new Map();
    for (const site of entry.sites) {
      const key = siteKey(site);
      keys.set(key, (keys.get(key) ?? 0) + 1);
    }
    byFile.set(entry.file, keys);
  }
  return byFile;
}

// Given a file's relative path + source and the baseline map, return the
// sites NOT covered by the file's baseline entries (i.e. new debt). Each
// scanned site consumes at most one baseline entry with the same context and
// value, so an inserted literal fails even in a file that has a baseline
// entry — including an exact duplicate of an existing site.
function evaluate(relFile, code, baselineSites) {
  const remaining = new Map(baselineSites.get(relFile) ?? []);
  const fresh = [];
  for (const site of scanSource(code, relFile)) {
    const key = siteKey(site);
    const available = remaining.get(key) ?? 0;
    if (available > 0) {
      remaining.set(key, available - 1);
    } else {
      fresh.push(site);
    }
  }
  return fresh;
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

// { rel -> [{ context, sizes }] } of every numeric-fontSize site in the live
// tree (for --list / baseline regeneration).
function scanTree(root) {
  const files = {};
  for (const abs of collectFiles(root)) {
    const sites = scanSource(fs.readFileSync(abs, "utf8"), relOf(abs));
    if (sites.length) {
      files[relOf(abs)] = sites.map(({ context, sizes }) => ({ context, sizes }));
    }
  }
  return files;
}

function main(argv) {
  if (argv.includes("--list")) {
    const files = scanTree(MOBILE_ROOT);
    console.log(JSON.stringify(files, null, 2));
    return;
  }

  const baselineSites = loadBaselineSites(DEFAULT_BASELINE_PATH);
  const failures = [];
  for (const abs of collectFiles(MOBILE_ROOT)) {
    const rel = relOf(abs);
    const fresh = evaluate(rel, fs.readFileSync(abs, "utf8"), baselineSites);
    if (fresh.length) failures.push({ file: rel, fresh });
  }

  if (failures.length) {
    console.error(
      "✖ fontSize guard: numeric fontSize literal not covered by the tracked baseline.",
    );
    console.error(
      "  Reference a theme/typography.ts typeScale token instead (e.g. typeScale.body).",
    );
    for (const f of failures) {
      for (const site of f.fresh) {
        console.error(
          `  ${f.file}:${site.line} — fontSize ${site.sizes.join("/")} in \`${site.context}\` has no baseline entry`,
        );
      }
    }
    console.error(
      "  The baseline (font-size-baseline.json) only shrinks: route the size through typeScale rather than adding an entry.",
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
  collectNumericFontSizes,
  siteKey,
  scanSource,
  evaluate,
  loadBaselineSites,
  collectFiles,
  scanTree,
};
