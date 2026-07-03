"use strict";

const fs = require("fs");

const {
  scanSource,
  evaluate,
  loadBaselineCounts,
  scanTree,
  MOBILE_ROOT,
  DEFAULT_BASELINE_PATH,
} = require("./check-accent-as-text");

// A file with no baseline entry (count defaults to 0), so any accent-as-text
// site is a fresh violation.
const UNLISTED = "components/Unlisted.tsx";

describe("scanSource — direction of the guard", () => {
  it("fails on `color: colors.accent` used as a text color", () => {
    expect(scanSource("const s = { color: colors.accent };", UNLISTED)).toHaveLength(1);
  });

  it("fails on `color: colors.accent` inside a ternary", () => {
    expect(
      scanSource("const s = { color: selected ? colors.accent : colors.text };", UNLISTED),
    ).toHaveLength(1);
  });

  it("fails on `color: colors.accent` inside a `&&` / `??` expression", () => {
    expect(scanSource("const s = { color: on && colors.accent };", UNLISTED)).toHaveLength(1);
    expect(scanSource("const s = { color: c ?? colors.accent };", UNLISTED)).toHaveLength(1);
  });

  it("passes on `backgroundColor: colors.accent`", () => {
    expect(scanSource("const s = { backgroundColor: colors.accent };", UNLISTED)).toHaveLength(0);
  });

  it("passes on border/fill/stroke/trackColor uses of colors.accent", () => {
    expect(scanSource("const s = { borderColor: colors.accent };", UNLISTED)).toHaveLength(0);
    expect(
      scanSource("const s = { fill: colors.accent, stroke: colors.accent };", UNLISTED),
    ).toHaveLength(0);
    // Nested true/false keys of a trackColor object are not `color`.
    expect(
      scanSource(
        "const s = { trackColor: { true: colors.accent, false: colors.textSecondary } };",
        UNLISTED,
      ),
    ).toHaveLength(0);
  });

  it("passes on the AA-verified tokens colors.accentText / colors.accentForeground", () => {
    expect(scanSource("const s = { color: colors.accentText };", UNLISTED)).toHaveLength(0);
    expect(scanSource("const s = { color: colors.accentForeground };", UNLISTED)).toHaveLength(0);
    expect(
      scanSource("const s = { color: selected ? colors.accentText : colors.text };", UNLISTED),
    ).toHaveLength(0);
  });
});

describe("evaluate — per-file baseline count", () => {
  const baseline = new Map([["components/Foo.tsx", 1]]);

  it("exempts a file's first N sites (source order)", () => {
    expect(evaluate("components/Foo.tsx", "const a = { color: colors.accent };", baseline)).toEqual(
      [],
    );
  });

  it("flags sites beyond the baselined count", () => {
    const extra = evaluate(
      "components/Foo.tsx",
      "const a = { color: colors.accent };\nconst b = { color: colors.accent };",
      baseline,
    );
    expect(extra).toHaveLength(1);
  });

  it("flags any accent-as-text site in a file with no baseline entry", () => {
    expect(
      evaluate(UNLISTED, "const a = { color: colors.accent };", new Map()),
    ).toHaveLength(1);
  });
});

describe("accent-text-baseline.json", () => {
  const baseline = JSON.parse(fs.readFileSync(DEFAULT_BASELINE_PATH, "utf8"));

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

  it("covers the live tree exactly — make verify passes with the baseline present", () => {
    // The committed baseline is a snapshot of the guard's own output on the live
    // tree, so every remaining accent-as-text site is exempt and the guard is
    // green. Regressions (a live count that drifts from the baseline) fail here.
    const live = scanTree(MOBILE_ROOT);
    const baselineCounts = Object.fromEntries(
      [...loadBaselineCounts(DEFAULT_BASELINE_PATH).entries()].map(([f, c]) => [f, c]),
    );
    expect(live).toEqual(baselineCounts);
  });
});
