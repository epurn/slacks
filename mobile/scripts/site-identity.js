"use strict";
// Shared site-identity helpers for the baseline-aware verify-hook guards
// (check-font-size-literal.js, check-accent-as-text.js). A "site" is a
// pre-existing violation pinned in a JSON baseline so a guard can be adopted
// without a flag-day rewrite; both guards key a site by its enclosing
// style-key CONTEXT plus its VALUE(S), matched per file as a multiset, so a
// new site — or an exact duplicate of an existing one — can never hide behind
// an unrelated site being fixed in the same file (FTY-192, ported to the
// accent guard by FTY-230).

const ts = require("typescript");

// The site's identity within its file: the chain of enclosing property /
// variable names, outermost first (e.g. `styles.axisLabel`). Line numbers are
// too brittle for a baseline (any edit above shifts them); the style-key path
// survives unrelated edits while still distinguishing sites.
function contextOf(node) {
  const names = [];
  let cur = node.parent;
  while (cur) {
    if (
      ts.isPropertyAssignment(cur) &&
      (ts.isIdentifier(cur.name) || ts.isStringLiteral(cur.name))
    ) {
      names.unshift(cur.name.text);
    }
    if (ts.isVariableDeclaration(cur) && ts.isIdentifier(cur.name)) {
      names.unshift(cur.name.text);
    }
    cur = cur.parent;
  }
  return names.join(".") || "<anonymous>";
}

// A stable multiset key for one site: enclosing context + its already-sorted
// value(s), comma-joined. Callers sort their own values (numeric vs. string
// sites sort differently) and pass the result in.
function siteKey(context, sortedValues) {
  return `${context}@${sortedValues.join(",")}`;
}

module.exports = { contextOf, siteKey };
