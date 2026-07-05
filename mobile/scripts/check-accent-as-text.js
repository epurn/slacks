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
// Baseline-aware and SITE-BASED (ported from check-font-size-literal.js /
// FTY-192 by FTY-230): `accent-text-baseline.json` pins each pre-existing
// accent-as-text site by its enclosing style-key context (e.g.
// `styles.axisLabel`) plus its accent-access value(s) (e.g. `colors.accent`),
// so the guard can be adopted without a flag-day rewrite. Sites are matched
// per file as a multiset of `context@values` keys: a scanned site is exempt
// only if the file's baseline still has an unconsumed entry with the same
// context and value. Any NEW site — a new style key, a different accent
// accessor, a duplicate of an existing site, or any site in an unlisted file
// — fails. Per-screen stories drain a file's site entries (and then the file
// entry) as they swap to colors.accentText; the guard is fully strict once
// this list is empty (it already is, as of FTY-207-212).
//
// Usage:
//   node scripts/check-accent-as-text.js          # verify; exit 1 on new sites
//   node scripts/check-accent-as-text.js --list    # print the live per-file sites
"use strict";

const fs = require("fs");
const path = require("path");
const ts = require("typescript");
const { contextOf, siteKey: sharedSiteKey } = require("./site-identity");

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

// Collects the source text of every leaf `<x>.accent` member access reachable
// from a `color: <expr>` value (e.g. `color: colors.accent`, both arms of
// `selected ? colors.accent : colors.text`, the operands of `&&` / `||` /
// `??`) — but not token references like `colors.accentText`. Returns the
// values found, [] when the expression holds no accent-as-text access.
function collectAccentAccesses(node, out = []) {
  if (!node) return out;
  if (ts.isParenthesizedExpression(node)) {
    return collectAccentAccesses(node.expression, out);
  }
  if (ts.isConditionalExpression(node)) {
    collectAccentAccesses(node.whenTrue, out);
    collectAccentAccesses(node.whenFalse, out);
    return out;
  }
  if (ts.isBinaryExpression(node)) {
    const op = node.operatorToken.kind;
    if (
      op === ts.SyntaxKind.AmpersandAmpersandToken ||
      op === ts.SyntaxKind.BarBarToken ||
      op === ts.SyntaxKind.QuestionQuestionToken
    ) {
      collectAccentAccesses(node.left, out);
      collectAccentAccesses(node.right, out);
    }
    return out;
  }
  if (
    ts.isPropertyAccessExpression(node) &&
    node.name.kind === ts.SyntaxKind.Identifier &&
    node.name.text === "accent"
  ) {
    out.push(node.getText());
  }
  return out;
}

// True when a `color: <expr>` value references `.accent` anywhere reachable
// from it. Kept as a thin wrapper over collectAccentAccesses for readability.
function referencesAccentAsText(node) {
  return collectAccentAccesses(node).length > 0;
}

// True when the property key is literally `color` (identifier or string key),
// not a computed key and not `backgroundColor` / `borderColor` / etc.
function nameIsColor(name) {
  if (ts.isIdentifier(name)) return name.text === "color";
  if (ts.isStringLiteral(name)) return name.text === "color";
  return false;
}

// A stable multiset key for one site: enclosing context + sorted values.
// contextOf (the enclosing style-key chain) is shared with
// check-font-size-literal.js via ./site-identity.
function siteKey(site) {
  return sharedSiteKey(site.context, [...site.values].sort());
}

// Scan a single source string; returns every accent-as-text site, in source
// order, as { line, context, values }.
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
    if (ts.isPropertyAssignment(node) && nameIsColor(node.name)) {
      const values = collectAccentAccesses(node.initializer);
      if (values.length) {
        sites.push({
          pos: node.getStart(sourceFile),
          line: sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile)).line + 1,
          context: contextOf(node),
          values,
        });
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  sites.sort((a, b) => a.pos - b.pos);
  return sites.map(({ line, context, values }) => ({ line, context, values }));
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
// value, so an inserted site fails even in a file that has a baseline entry
// — including an exact duplicate of an existing site.
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

// { rel -> [{ context, values }] } of every accent-as-text site in the live
// tree (for --list / baseline regeneration).
function scanTree(root) {
  const files = {};
  for (const abs of collectFiles(root)) {
    const sites = scanSource(fs.readFileSync(abs, "utf8"), relOf(abs));
    if (sites.length) {
      files[relOf(abs)] = sites.map(({ context, values }) => ({ context, values }));
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
      "✖ accent-as-text guard: colors.accent used as a text color beyond the tracked baseline.",
    );
    console.error(
      "  accent fails WCAG AA as text on the light surface — use colors.accentText instead.",
    );
    console.error(
      "  (backgroundColor / borderColor / fill / stroke uses of colors.accent are fine.)",
    );
    for (const f of failures) {
      for (const site of f.fresh) {
        console.error(
          `  ${f.file}:${site.line} — ${site.values.join("/")} as text in \`${site.context}\` has no baseline entry`,
        );
      }
    }
    console.error(
      "  The baseline (accent-text-baseline.json) only shrinks: swap to colors.accentText rather than adding an entry.",
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
  siteKey,
  scanSource,
  evaluate,
  loadBaselineSites,
  collectFiles,
  scanTree,
};
