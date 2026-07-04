"use strict";

const fs = require("fs");

const {
  scanSource,
  evaluate,
  loadBaselineCounts,
  scanTree,
  MOBILE_ROOT,
  DEFAULT_BASELINE_PATH,
} = require("./check-font-size-literal");

// A file with no baseline entry (count defaults to 0), so any numeric
// fontSize site is a fresh violation.
const UNLISTED = "components/Unlisted.tsx";

describe("scanSource — direction of the guard", () => {
  it("fails on a numeric `fontSize: N` literal", () => {
    expect(scanSource("const s = { fontSize: 20 };", UNLISTED)).toHaveLength(1);
  });

  it("fails on a numeric fontSize inside a ternary", () => {
    expect(
      scanSource("const s = { fontSize: selected ? 20 : 16 };", UNLISTED),
    ).toHaveLength(1);
  });

  it("fails on a numeric fontSize inside a `&&` / `??` expression", () => {
    expect(scanSource("const s = { fontSize: on && 20 };", UNLISTED)).toHaveLength(1);
    expect(scanSource("const s = { fontSize: c ?? 20 };", UNLISTED)).toHaveLength(1);
  });

  it("passes on `fontSize: typeScale.body`", () => {
    expect(scanSource("const s = { fontSize: typeScale.body };", UNLISTED)).toHaveLength(0);
  });

  it("passes on `fontSize: typeScale[scale]`", () => {
    expect(scanSource("const s = { fontSize: typeScale[scale] };", UNLISTED)).toHaveLength(0);
  });

  it("passes on a ternary between typeScale tokens", () => {
    expect(
      scanSource(
        "const s = { fontSize: selected ? typeScale.title1 : typeScale.body };",
        UNLISTED,
      ),
    ).toHaveLength(0);
  });

  it("ignores unrelated numeric properties (e.g. lineHeight, width)", () => {
    expect(scanSource("const s = { lineHeight: 20, width: 44 };", UNLISTED)).toHaveLength(0);
  });
});

describe("evaluate — per-file baseline count", () => {
  const baseline = new Map([["components/Foo.tsx", 1]]);

  it("exempts a file's first N sites (source order)", () => {
    expect(evaluate("components/Foo.tsx", "const a = { fontSize: 20 };", baseline)).toEqual([]);
  });

  it("flags sites beyond the baselined count", () => {
    const extra = evaluate(
      "components/Foo.tsx",
      "const a = { fontSize: 20 };\nconst b = { fontSize: 16 };",
      baseline,
    );
    expect(extra).toHaveLength(1);
  });

  it("flags any numeric fontSize site in a file with no baseline entry", () => {
    expect(evaluate(UNLISTED, "const a = { fontSize: 20 };", new Map())).toHaveLength(1);
  });
});

describe("font-size-baseline.json", () => {
  const baseline = JSON.parse(fs.readFileSync(DEFAULT_BASELINE_PATH, "utf8"));

  it("does not baseline the shared-owned sites fixed in this story", () => {
    const baselinedFiles = new Set(baseline.sites.map((site) => site.file));
    expect(baselinedFiles.has("components/CalorieHero.tsx")).toBe(false);
    expect(baselinedFiles.has("components/DailySummary.tsx")).toBe(false);
    expect(baselinedFiles.has("components/MacroTier.tsx")).toBe(false);
    expect(baselinedFiles.has("app/day.tsx")).toBe(false);
    expect(baselinedFiles.has("components/ui/ThemedNumber.tsx")).toBe(false);
    expect(baselinedFiles.has("components/ui/DisplayText.tsx")).toBe(false);
  });

  it("enumerates the currently-known per-screen numeric fontSize sites", () => {
    const byFile = Object.fromEntries(baseline.sites.map((site) => [site.file, site.count]));
    expect(byFile).toEqual({
      "components/ConfirmParsedValuesSheet.tsx": 1,
      "components/EntryRow.tsx": 7,
      "components/StatusIcon.tsx": 1,
      "components/TypeaheadSuggestionBar.tsx": 1,
      "components/today/SignInRequired.tsx": 1,
      "components/CorrectionSheet.tsx": 1,
      "components/correction/AdvancedLeverRow.tsx": 1,
      "components/correction/AmountStepper.tsx": 1,
      "components/correction/ChangeMatchPanel.tsx": 1,
      "components/WeightEntryInput.tsx": 4,
      "components/WeightScreen.tsx": 4,
      "components/WeightTrendChart.tsx": 5,
      "components/BarcodeScannerScreen.tsx": 2,
      "components/CameraCapture.tsx": 3,
      "components/LabelCaptureScreen.tsx": 6,
      "components/EWMATrendChart.tsx": 5,
    });
  });

  it("covers the live tree exactly — make verify passes with the baseline present", () => {
    // The committed baseline is a snapshot of the guard's own output on the live
    // tree, so every remaining numeric fontSize site is exempt and the guard is
    // green. Regressions (a live count that drifts from the baseline) fail here.
    const live = scanTree(MOBILE_ROOT);
    const baselineCounts = Object.fromEntries(
      [...loadBaselineCounts(DEFAULT_BASELINE_PATH).entries()].map(([f, c]) => [f, c]),
    );
    expect(live).toEqual(baselineCounts);
  });
});
