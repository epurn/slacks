"use strict";

const fs = require("fs");
const path = require("path");

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

  it("does not baseline components/WeightLogSheet.tsx — drained by FTY-210", () => {
    expect(
      baseline.sites.some((site) => site.file === "components/WeightLogSheet.tsx"),
    ).toBe(false);
  });

  it("does not baseline the Today-owned files drained by FTY-207 — they are fixed, not deferred", () => {
    const baselinedFiles = baseline.sites.map((site) => site.file);
    expect(baselinedFiles).not.toContain("components/EntryRow.tsx");
    expect(baselinedFiles).not.toContain("components/ConfirmParsedValuesSheet.tsx");
  });

  it("enumerates the currently-known per-screen accent-as-text sites", () => {
    const byFile = Object.fromEntries(baseline.sites.map((site) => [site.file, site.count]));
    expect(byFile).toEqual({
      "components/CorrectionSheet.tsx": 2,
      "components/TrendsScreen.tsx": 1,
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

describe("FTY-207 — Today-owned accent-as-text sites are fully drained", () => {
  // The Today-owned files: the row/status/banner/suggestion components at
  // components/, the today screen host + its sheets under components/today/,
  // and ConfirmParsedValuesSheet.tsx — a Today sheet mounted from
  // components/today/TodaySheetHost.tsx that lives at components/ (not
  // components/today/), so a components/today/ glob alone would miss it.
  const TODAY_OWNED_FILES = [
    "components/EntryRow.tsx",
    "components/OfflineEntryRow.tsx",
    "components/ItemTimelineRow.tsx",
    "components/TypeaheadSuggestionBar.tsx",
    "components/StatusIcon.tsx",
    "components/ConnectionBanner.tsx",
    "components/TodayScreen.tsx",
    "components/ConfirmParsedValuesSheet.tsx",
    "components/today/ClusterView.tsx",
    "components/today/SignInRequired.tsx",
    "components/today/Timeline.tsx",
    "components/today/TodayComposer.tsx",
    "components/today/TodaySheetHost.tsx",
  ];

  it("has no remaining color: colors.accent text site in any Today-owned file", () => {
    for (const rel of TODAY_OWNED_FILES) {
      const abs = path.join(MOBILE_ROOT, rel);
      const lines = scanSource(fs.readFileSync(abs, "utf8"), rel);
      expect({ file: rel, lines }).toEqual({ file: rel, lines: [] });
    }
  });

  it("leaves ConfirmParsedValuesSheet.tsx's backgroundColor: colors.accent fill sites untouched", () => {
    const code = fs.readFileSync(
      path.join(MOBILE_ROOT, "components/ConfirmParsedValuesSheet.tsx"),
      "utf8",
    );
    const fillSites = code.match(/backgroundColor: colors\.accent\b/g) ?? [];
    expect(fillSites.length).toBeGreaterThanOrEqual(2);
  });
});
