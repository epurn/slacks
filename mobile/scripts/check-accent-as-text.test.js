"use strict";

const fs = require("fs");
const path = require("path");

const {
  scanSource,
  evaluate,
  loadBaselineSites,
  siteKey,
  scanTree,
  MOBILE_ROOT,
  DEFAULT_BASELINE_PATH,
} = require("./check-accent-as-text");
const { siteKey: sharedSiteKey } = require("./site-identity");
const fontSizeGuard = require("./check-font-size-literal");

// A file with no baseline entry, so any accent-as-text site is a fresh
// violation.
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

  it("identifies each site by its enclosing style-key context and accent-access value", () => {
    const sites = scanSource(
      "const styles = StyleSheet.create({ label: { color: colors.accent } });",
      UNLISTED,
    );
    expect(sites).toEqual([{ line: 1, context: "styles.label", values: ["colors.accent"] }]);
  });
});

describe("evaluate — site-based baseline matching", () => {
  // components/Foo.tsx has exactly one known site: `styles.title` referencing
  // `colors.accent`.
  const baseline = new Map([
    ["components/Foo.tsx", new Map([["styles.title@colors.accent", 1]])],
  ]);

  it("exempts a baselined site (same context and value)", () => {
    expect(
      evaluate(
        "components/Foo.tsx",
        "const styles = { title: { color: colors.accent } };",
        baseline,
      ),
    ).toEqual([]);
  });

  it("flags a NEW site inserted into a file that already has a baseline entry", () => {
    const fresh = evaluate(
      "components/Foo.tsx",
      "const styles = { title: { color: colors.accent }, badge: { color: colors.accent } };",
      baseline,
    );
    expect(fresh).toHaveLength(1);
    expect(fresh[0].context).toBe("styles.badge");
  });

  it("flags a new site even when it duplicates a baselined site exactly", () => {
    // Both sites key as `rows.s@colors.accent`, but the baseline holds only
    // one entry — the multiset match lets the first consume it and fails the
    // second (the regression the count-based model missed).
    const fresh = evaluate(
      "components/Foo.tsx",
      "const rows = [{ s: { color: colors.accent } }, { s: { color: colors.accent } }];",
      new Map([["components/Foo.tsx", new Map([["rows.s@colors.accent", 1]])]]),
    );
    expect(fresh).toHaveLength(1);
  });

  it("flags a baselined context whose accent accessor changed (baseline never grows)", () => {
    const fresh = evaluate(
      "components/Foo.tsx",
      "const styles = { title: { color: theme.accent } };",
      baseline,
    );
    expect(fresh).toHaveLength(1);
    expect(fresh[0].values).toEqual(["theme.accent"]);
  });

  it("flags any accent-as-text site in a file with no baseline entry", () => {
    expect(evaluate(UNLISTED, "const a = { color: colors.accent };", new Map())).toHaveLength(1);
  });
});

describe("accent-text-baseline.json", () => {
  const baseline = JSON.parse(fs.readFileSync(DEFAULT_BASELINE_PATH, "utf8"));

  it("does not baseline app/day.tsx — it is fixed in this story, not deferred", () => {
    expect(baseline.files.some((entry) => entry.file === "app/day.tsx")).toBe(false);
  });

  it("does not baseline components/WeightLogSheet.tsx — drained by FTY-210", () => {
    expect(
      baseline.files.some((entry) => entry.file === "components/WeightLogSheet.tsx"),
    ).toBe(false);
  });

  it("does not baseline the Today-owned files drained by FTY-207 — they are fixed, not deferred", () => {
    const baselinedFiles = baseline.files.map((entry) => entry.file);
    expect(baselinedFiles).not.toContain("components/EntryRow.tsx");
    expect(baselinedFiles).not.toContain("components/ConfirmParsedValuesSheet.tsx");
  });

  it("does not baseline components/TrendsScreen.tsx — drained by FTY-209", () => {
    expect(
      baseline.files.some((entry) => entry.file === "components/TrendsScreen.tsx"),
    ).toBe(false);
  });

  it("does not baseline the correction-owned files drained by FTY-208 — they are fixed, not deferred", () => {
    const baselinedFiles = baseline.files.map((entry) => entry.file);
    expect(baselinedFiles).not.toContain("components/CorrectionSheet.tsx");
    expect(baselinedFiles).not.toContain("components/correction/ChangeMatchPanel.tsx");
    expect(baselinedFiles).not.toContain("components/correction/ProvenanceBlock.tsx");
    expect(baselinedFiles).not.toContain("components/correction/SaveFoodRow.tsx");
  });

  it("does not baseline components/settings/BodySection.tsx — drained by FTY-212", () => {
    expect(
      baseline.files.some((entry) => entry.file === "components/settings/BodySection.tsx"),
    ).toBe(false);
  });

  it("does not baseline components/onboarding/MeasurementsStep.tsx — drained by FTY-211", () => {
    expect(
      baseline.files.some((entry) => entry.file === "components/onboarding/MeasurementsStep.tsx"),
    ).toBe(false);
  });

  it("enumerates the currently-known per-screen accent-as-text sites", () => {
    const byFile = Object.fromEntries(
      baseline.files.map((entry) => [entry.file, entry.sites.length]),
    );
    expect(byFile).toEqual({});
  });

  it("pins every baselined site by context and value, not by count", () => {
    for (const entry of baseline.files) {
      expect(entry.sites.length).toBeGreaterThan(0);
      for (const site of entry.sites) {
        expect(typeof site.context).toBe("string");
        expect(site.context.length).toBeGreaterThan(0);
        expect(Array.isArray(site.values)).toBe(true);
        expect(site.values.length).toBeGreaterThan(0);
      }
    }
  });

  it("covers the live tree exactly — make verify passes with the baseline present", () => {
    // The committed baseline is a snapshot of the guard's own output on the live
    // tree, so every remaining accent-as-text site is exempt and the guard is
    // green. Drift in either direction (a new site, or a stale entry for a
    // removed site) fails here.
    const live = scanTree(MOBILE_ROOT);
    const baselined = Object.fromEntries(baseline.files.map((entry) => [entry.file, entry.sites]));
    expect(live).toEqual(baselined);
  });

  it("loads into a per-file multiset keyed by context@values", () => {
    // Checked against whatever the baseline currently holds rather than a
    // named file: other lanes drain entries independently, and pinning one
    // breaks on their merges.
    const byFile = loadBaselineSites(DEFAULT_BASELINE_PATH);
    expect(byFile.size).toBe(baseline.files.length);
    for (const entry of baseline.files) {
      const multiset = byFile.get(entry.file);
      expect(multiset).toBeDefined();
      expect([...multiset.values()].reduce((a, b) => a + b, 0)).toBe(entry.sites.length);
    }
  });
});

describe("site-identity — shared between the accent and fontSize guards", () => {
  it("computes an identical site key format via the shared helper for the same context+value", () => {
    expect(siteKey({ context: "styles.a", values: ["colors.accent"] })).toBe(
      sharedSiteKey("styles.a", ["colors.accent"]),
    );
    expect(fontSizeGuard.siteKey({ context: "styles.a", sizes: [20] })).toBe(
      sharedSiteKey("styles.a", [20]),
    );
    // Same context + same value: both guards produce the exact same key, since
    // both delegate their formatting to the one shared helper.
    expect(siteKey({ context: "styles.a", values: [20] })).toBe(
      fontSizeGuard.siteKey({ context: "styles.a", sizes: [20] }),
    );
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

describe("FTY-208 — correction-owned accent-as-text sites are fully drained", () => {
  // The correction-owned files: the sheet host at components/, and its
  // change-match / provenance / save-food panels under components/correction/.
  const CORRECTION_OWNED_FILES = [
    "components/CorrectionSheet.tsx",
    "components/correction/ChangeMatchPanel.tsx",
    "components/correction/ProvenanceBlock.tsx",
    "components/correction/SaveFoodRow.tsx",
  ];

  it("has no remaining color: colors.accent text site in any correction-owned file", () => {
    for (const rel of CORRECTION_OWNED_FILES) {
      const abs = path.join(MOBILE_ROOT, rel);
      const lines = scanSource(fs.readFileSync(abs, "utf8"), rel);
      expect({ file: rel, lines }).toEqual({ file: rel, lines: [] });
    }
  });

  it("leaves OverridePanel.tsx's backgroundColor: colors.accent fill site untouched", () => {
    const code = fs.readFileSync(
      path.join(MOBILE_ROOT, "components/correction/OverridePanel.tsx"),
      "utf8",
    );
    const fillSites = code.match(/backgroundColor: colors\.accent\b/g) ?? [];
    expect(fillSites.length).toBeGreaterThanOrEqual(1);
  });

  it("leaves ClarifyMode.tsx's backgroundColor: colors.accent fill site untouched", () => {
    const code = fs.readFileSync(path.join(MOBILE_ROOT, "components/ClarifyMode.tsx"), "utf8");
    const fillSites = code.match(/backgroundColor:[^}]*colors\.accent\b/g) ?? [];
    expect(fillSites.length).toBeGreaterThanOrEqual(1);
  });
});

describe("FTY-212 — settings-owned accent-as-text sites are fully drained", () => {
  // The settings-owned files: the screen host at components/, and its
  // section/row/primitive components under components/settings/.
  const SETTINGS_OWNED_FILES = [
    "components/SettingsScreen.tsx",
    "components/settings/AccountSection.tsx",
    "components/settings/BodySection.tsx",
    "components/settings/DataAboutSection.tsx",
    "components/settings/MiniTargetReveal.tsx",
    "components/settings/OverrideEditCard.tsx",
    "components/settings/PreferencesSection.tsx",
    "components/settings/StateScreens.tsx",
    "components/settings/TargetRow.tsx",
    "components/settings/YouSection.tsx",
    "components/settings/primitives.tsx",
  ];

  it("has no remaining color: colors.accent text site in any settings-owned file", () => {
    for (const rel of SETTINGS_OWNED_FILES) {
      const abs = path.join(MOBILE_ROOT, rel);
      const lines = scanSource(fs.readFileSync(abs, "utf8"), rel);
      expect({ file: rel, lines }).toEqual({ file: rel, lines: [] });
    }
  });

  it("leaves BodySection.tsx's borderColor: colors.accent selection-ring site untouched", () => {
    const code = fs.readFileSync(
      path.join(MOBILE_ROOT, "components/settings/BodySection.tsx"),
      "utf8",
    );
    const borderSites = code.match(/borderColor: selected \? colors\.accent\b/g) ?? [];
    expect(borderSites.length).toBeGreaterThanOrEqual(1);
  });
});

describe("FTY-211 — onboarding-owned accent-as-text sites are fully drained", () => {
  // The onboarding-owned files: the wizard host at components/OnboardingScreen.tsx,
  // and its step/primitive components under components/onboarding/.
  const ONBOARDING_OWNED_FILES = [
    "components/OnboardingScreen.tsx",
    "components/onboarding/GoalStep.tsx",
    "components/onboarding/MeasurementsStep.tsx",
    "components/onboarding/TargetRevealStep.tsx",
    "components/onboarding/primitives.tsx",
  ];

  it("has no remaining color: colors.accent text site in any onboarding-owned file", () => {
    for (const rel of ONBOARDING_OWNED_FILES) {
      const abs = path.join(MOBILE_ROOT, rel);
      const lines = scanSource(fs.readFileSync(abs, "utf8"), rel);
      expect({ file: rel, lines }).toEqual({ file: rel, lines: [] });
    }
  });

  it("leaves MeasurementsStep.tsx's borderColor: colors.accent selection site untouched", () => {
    const code = fs.readFileSync(
      path.join(MOBILE_ROOT, "components/onboarding/MeasurementsStep.tsx"),
      "utf8",
    );
    const borderSites = code.match(/borderColor: selected\s*\?\s*colors\.accent\b/g) ?? [];
    expect(borderSites.length).toBeGreaterThanOrEqual(1);
  });

  it("leaves primitives.tsx's backgroundColor: colors.accent step-progress dot untouched", () => {
    const code = fs.readFileSync(
      path.join(MOBILE_ROOT, "components/onboarding/primitives.tsx"),
      "utf8",
    );
    const fillSites = code.match(/backgroundColor:\s*\n?\s*active \|\| done \? colors\.accent\b/g) ?? [];
    expect(fillSites.length).toBeGreaterThanOrEqual(1);
  });
});
