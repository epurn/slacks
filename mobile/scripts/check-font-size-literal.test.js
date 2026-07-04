"use strict";

const fs = require("fs");

const {
  scanSource,
  evaluate,
  loadBaselineSites,
  scanTree,
  MOBILE_ROOT,
  DEFAULT_BASELINE_PATH,
} = require("./check-font-size-literal");

// A file with no baseline entry, so any numeric fontSize site is a fresh
// violation.
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

  it("identifies each site by its enclosing style-key context and value", () => {
    const sites = scanSource(
      "const styles = StyleSheet.create({ axisLabel: { fontSize: 11 } });",
      UNLISTED,
    );
    expect(sites).toEqual([{ line: 1, context: "styles.axisLabel", sizes: [11] }]);
  });
});

describe("evaluate — site-based baseline matching", () => {
  // components/Foo.tsx has exactly one known site: `styles.title` at size 20.
  const baseline = new Map([["components/Foo.tsx", new Map([["styles.title@20", 1]])]]);

  it("exempts a baselined site (same context and value)", () => {
    expect(
      evaluate(
        "components/Foo.tsx",
        "const styles = { title: { fontSize: 20 } };",
        baseline,
      ),
    ).toEqual([]);
  });

  it("flags a NEW literal inserted into a file that already has a baseline entry", () => {
    const fresh = evaluate(
      "components/Foo.tsx",
      "const styles = { title: { fontSize: 20 }, badge: { fontSize: 12 } };",
      baseline,
    );
    expect(fresh).toHaveLength(1);
    expect(fresh[0].context).toBe("styles.badge");
  });

  it("flags a new literal even when it duplicates a baselined site exactly", () => {
    // Both sites key as `rows.s@20`, but the baseline holds only one entry —
    // the multiset match lets the first consume it and fails the second.
    const fresh = evaluate(
      "components/Foo.tsx",
      "const rows = [{ s: { fontSize: 20 } }, { s: { fontSize: 20 } }];",
      new Map([["components/Foo.tsx", new Map([["rows.s@20", 1]])]]),
    );
    expect(fresh).toHaveLength(1);
  });

  it("flags a baselined context whose size changed (baseline never grows)", () => {
    const fresh = evaluate(
      "components/Foo.tsx",
      "const styles = { title: { fontSize: 24 } };",
      baseline,
    );
    expect(fresh).toHaveLength(1);
    expect(fresh[0].sizes).toEqual([24]);
  });

  it("flags any numeric fontSize site in a file with no baseline entry", () => {
    expect(evaluate(UNLISTED, "const a = { fontSize: 20 };", new Map())).toHaveLength(1);
  });
});

describe("font-size-baseline.json", () => {
  const baseline = JSON.parse(fs.readFileSync(DEFAULT_BASELINE_PATH, "utf8"));

  it("does not baseline the shared-owned sites fixed in this story", () => {
    const baselinedFiles = new Set(baseline.files.map((entry) => entry.file));
    expect(baselinedFiles.has("components/CalorieHero.tsx")).toBe(false);
    expect(baselinedFiles.has("components/DailySummary.tsx")).toBe(false);
    expect(baselinedFiles.has("components/MacroTier.tsx")).toBe(false);
    expect(baselinedFiles.has("app/day.tsx")).toBe(false);
    expect(baselinedFiles.has("components/ui/ThemedNumber.tsx")).toBe(false);
    expect(baselinedFiles.has("components/ui/DisplayText.tsx")).toBe(false);
  });

  it("does not baseline the capture sites drained by FTY-216", () => {
    const baselinedFiles = new Set(baseline.files.map((entry) => entry.file));
    expect(baselinedFiles.has("components/BarcodeScannerScreen.tsx")).toBe(false);
    expect(baselinedFiles.has("components/CameraCapture.tsx")).toBe(false);
    expect(baselinedFiles.has("components/LabelCaptureScreen.tsx")).toBe(false);
  });

  it("enumerates the currently-known per-screen numeric fontSize sites", () => {
    const byFile = Object.fromEntries(
      baseline.files.map((entry) => [entry.file, entry.sites.length]),
    );
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
      "components/EWMATrendChart.tsx": 5,
    });
  });

  it("pins every baselined site by context and value, not by count", () => {
    for (const entry of baseline.files) {
      expect(entry.sites.length).toBeGreaterThan(0);
      for (const site of entry.sites) {
        expect(typeof site.context).toBe("string");
        expect(site.context.length).toBeGreaterThan(0);
        expect(Array.isArray(site.sizes)).toBe(true);
        expect(site.sizes.length).toBeGreaterThan(0);
      }
    }
  });

  it("covers the live tree exactly — make verify passes with the baseline present", () => {
    // The committed baseline is a snapshot of the guard's own output on the live
    // tree, so every remaining numeric fontSize site is exempt and the guard is
    // green. Drift in either direction (a new site, or a stale entry for a
    // removed site) fails here.
    const live = scanTree(MOBILE_ROOT);
    const baselined = Object.fromEntries(
      baseline.files.map((entry) => [entry.file, entry.sites]),
    );
    expect(live).toEqual(baselined);
  });

  it("loads into a per-file multiset keyed by context@sizes", () => {
    const byFile = loadBaselineSites(DEFAULT_BASELINE_PATH);
    const entryRow = byFile.get("components/EntryRow.tsx");
    expect(entryRow).toBeDefined();
    expect([...entryRow.values()].reduce((a, b) => a + b, 0)).toBe(7);
  });
});
