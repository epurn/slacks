"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { RuleTester } = require("eslint");
const { createRule, MOBILE_ROOT } = require("./no-accent-as-text");

function fixtureBaseline(sites) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "accent-text-baseline-"));
  const file = path.join(dir, "baseline.json");
  fs.writeFileSync(file, JSON.stringify({ version: 1, sites }));
  return file;
}

const ruleTester = new RuleTester({
  languageOptions: { ecmaVersion: 2022, sourceType: "module" },
});

// RuleTester.run() drives its own describe/it blocks (it auto-detects the
// Jest test framework), so these calls sit at the top level rather than
// nested inside another it() — nesting throws "Tests cannot be nested".

ruleTester.run("no-accent-as-text", createRule(fixtureBaseline([])), {
  valid: [
    { code: "const s = { backgroundColor: colors.accent };", filename: "components/Unlisted.tsx" },
    { code: "const s = { borderColor: colors.accent };", filename: "components/Unlisted.tsx" },
    { code: "const s = { color: colors.accentText };", filename: "components/Unlisted.tsx" },
    { code: "const s = { color: colors.accentForeground };", filename: "components/Unlisted.tsx" },
    {
      code: "const s = { color: selected ? colors.accentText : colors.text };",
      filename: "components/Unlisted.tsx",
    },
    {
      // Nested "true"/"false" keys of a trackColor object are not "color".
      code: 'const s = { trackColor: { true: colors.accent, false: colors.textSecondary } };',
      filename: "components/Unlisted.tsx",
    },
    { code: "const s = { fill: colors.accent, stroke: colors.accent };", filename: "components/Unlisted.tsx" },
  ],
  invalid: [
    {
      code: "const s = { color: colors.accent };",
      filename: "components/Unlisted.tsx",
      errors: [{ messageId: "accentAsText" }],
    },
    {
      code: "const s = { color: selected ? colors.accent : colors.text };",
      filename: "components/Unlisted.tsx",
      errors: [{ messageId: "accentAsText" }],
    },
  ],
});

ruleTester.run(
  "no-accent-as-text (baseline)",
  createRule(fixtureBaseline([{ file: "components/Foo.tsx", count: 1, reason: "test fixture" }])),
  {
    valid: [
      {
        // Exactly at the baselined count — allowed.
        code: "const a = { color: colors.accent };",
        filename: "components/Foo.tsx",
      },
    ],
    invalid: [
      {
        // Second site in this file exceeds the baselined count of 1.
        code: "const a = { color: colors.accent }; const b = { color: colors.accent };",
        filename: "components/Foo.tsx",
        errors: [{ messageId: "accentAsText" }],
      },
    ],
  },
);

ruleTester.run(
  "no-accent-as-text (absolute filename)",
  createRule(fixtureBaseline([{ file: "components/Bar.tsx", count: 1, reason: "test fixture" }])),
  {
    valid: [
      {
        code: "const a = { color: colors.accent };",
        filename: path.join(MOBILE_ROOT, "components/Bar.tsx"),
      },
    ],
    invalid: [],
  },
);

describe("accent-text-baseline.json", () => {
  const baseline = JSON.parse(
    fs.readFileSync(path.join(MOBILE_ROOT, "accent-text-baseline.json"), "utf8"),
  );

  it("does not baseline app/day.tsx — it is fixed in this story, not deferred", () => {
    expect(baseline.sites.some((site) => site.file === "app/day.tsx")).toBe(false);
  });

  it("enumerates the currently-known per-screen accent-as-text sites", () => {
    const byFile = Object.fromEntries(baseline.sites.map((site) => [site.file, site.count]));
    expect(byFile).toEqual({
      "components/ConfirmParsedValuesSheet.tsx": 1,
      "components/CorrectionSheet.tsx": 2,
      "components/EntryRow.tsx": 3,
      "components/TrendsScreen.tsx": 1,
      "components/WeightLogSheet.tsx": 1,
      "components/correction/ChangeMatchPanel.tsx": 1,
      "components/correction/ProvenanceBlock.tsx": 1,
      "components/correction/SaveFoodRow.tsx": 1,
      "components/onboarding/MeasurementsStep.tsx": 1,
      "components/settings/BodySection.tsx": 1,
    });
  });
});
