// Custom ESLint rule: forbid `colors.accent` as a text `color:` value.
//
// `accent` fails WCAG AA as text on the light surface (prior-audit C-UX-1);
// `accentText` is the AA-verified token for that use (see theme/theme.test.ts).
// Background/border/fill uses of `accent` are unaffected — only the object
// property literally named `color` is checked.
//
// Baseline-aware: `accent-text-baseline.json` pins a per-file count of
// pre-existing violations so this rule can be adopted without a single
// flag-day rewrite. Each file's first N accent-as-text sites (in source
// order) are exempt, where N is that file's baseline count; anything beyond
// N — including a brand-new file with no baseline entry — fails. Per-screen
// stories drain their file's count to 0 (and remove the entry) as they swap
// their sites to `accentText`.
"use strict";

const fs = require("fs");
const path = require("path");

const MOBILE_ROOT = path.resolve(__dirname, "..");
const DEFAULT_BASELINE_PATH = path.join(MOBILE_ROOT, "accent-text-baseline.json");

function loadBaselineCounts(baselinePath) {
  const raw = fs.readFileSync(baselinePath, "utf8");
  const data = JSON.parse(raw);
  const counts = new Map();
  for (const site of data.sites) {
    counts.set(site.file, site.count);
  }
  return counts;
}

// Walks the value side of a `color: <expr>` property looking for a leaf
// member access ending in `.accent` (e.g. `colors.accent`, but not
// `colors.accentText` / `colors.accentForeground`).
function referencesAccentAsText(node) {
  if (!node) return false;
  switch (node.type) {
    case "ConditionalExpression":
      return referencesAccentAsText(node.consequent) || referencesAccentAsText(node.alternate);
    case "LogicalExpression":
      return referencesAccentAsText(node.left) || referencesAccentAsText(node.right);
    case "MemberExpression":
      return (
        !node.computed && node.property.type === "Identifier" && node.property.name === "accent"
      );
    default:
      return false;
  }
}

function keyName(key, computed) {
  if (computed) return null;
  if (key.type === "Identifier") return key.name;
  if (key.type === "Literal" && typeof key.value === "string") return key.value;
  return null;
}

function createRule(baselinePath) {
  const baselineCounts = loadBaselineCounts(baselinePath);

  return {
    meta: {
      type: "problem",
      docs: {
        description:
          "Disallow colors.accent as a text color (fails WCAG AA on light); use colors.accentText.",
      },
      schema: [],
      messages: {
        accentAsText:
          "colors.accent fails WCAG AA as text on the light surface — use colors.accentText instead. (Background/border/fill uses of colors.accent are fine.)",
      },
    },
    create(context) {
      const filename = context.filename ?? context.getFilename();
      const relFile = path.relative(MOBILE_ROOT, filename).split(path.sep).join("/");
      const allowed = baselineCounts.get(relFile) ?? 0;
      const violations = [];

      return {
        Property(node) {
          if (keyName(node.key, node.computed) !== "color") return;
          if (!referencesAccentAsText(node.value)) return;
          violations.push(node.key);
        },
        "Program:exit"() {
          for (const keyNode of violations.slice(allowed)) {
            context.report({ node: keyNode, messageId: "accentAsText" });
          }
        },
      };
    },
  };
}

module.exports = createRule(DEFAULT_BASELINE_PATH);
module.exports.createRule = createRule;
module.exports.MOBILE_ROOT = MOBILE_ROOT;
