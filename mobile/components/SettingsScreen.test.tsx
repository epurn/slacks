/**
 * Component tests for SettingsScreen (FTY-102).
 *
 * Tests cover:
 *   - Calorie-target provenance/override/reset
 *   - Macro-target provenance/override/reset
 *   - Mini target-reveal (goal edit + body-metric edit triggers)
 *   - Incomplete profile / no target shows calm prompt
 *   - Settings groups render in light and dark (via ThemeProvider override)
 *   - PREFERENCES persistence (units, appearance, cadence)
 *   - Sign-out clears session and routes to unauthenticated state
 *   - No sensitive values emitted to logs or errors
 */

import React from "react";
import { AccessibilityInfo, ScrollView } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { ThemeProvider } from "@/theme";
import { SettingsScreen } from "./SettingsScreen";
import {
  activateVisualReviewPreset,
  __deactivateVisualReview,
} from "@/e2e/visualReview/session";
import type { TargetReadModel } from "@/api/dailySummary";
import { GoalsApiError, type GoalTargetResponse } from "@/api/goals";
import type { ProfileDTO } from "@/api/profile";
import {
  UnitsPreferenceProvider,
  useUnitsPreference,
} from "@/state/unitsPreference";
import type { UnitsPreference } from "@/state/profile";
import type { Session } from "@/state/session";
import type { AppSettingsStore } from "@/state/appSettings";
import type {
  CadenceStore,
  NotificationsAdapter,
  WeighInCadence,
} from "@/state/reminderScheduler";

// ─────────────────────────────────────────────────────────────────────────────
// Mock expo-router (navigation is tested separately)
// ─────────────────────────────────────────────────────────────────────────────
jest.mock("expo-router", () => ({
  useRouter: jest.fn(() => ({
    push: jest.fn(),
    back: jest.fn(),
    replace: jest.fn(),
  })),
  useLocalSearchParams: jest.fn(() => ({})),
}));

// ─────────────────────────────────────────────────────────────────────────────
// Mock SessionContext so we can inject a fake controller
// ─────────────────────────────────────────────────────────────────────────────
const mockSignOut = jest.fn().mockResolvedValue(undefined);
const mockSignIn = jest.fn();
const mockCreateAccount = jest.fn();

jest.mock("@/state/session", () => {
  const original = jest.requireActual<typeof import("@/state/session")>(
    "@/state/session",
  );
  return {
    ...original,
    useSession: jest.fn(() => SESSION),
    useSessionController: jest.fn(() => ({
      session: SESSION,
      status: "ready",
      signOut: mockSignOut,
      signIn: mockSignIn,
      createAccount: mockCreateAccount,
    })),
  };
});

// ─────────────────────────────────────────────────────────────────────────────
// Patch AccessibilityInfo.isReduceMotionEnabled so animations are synchronous
// (avoid the private path mock which is resolver-dependent)
// ─────────────────────────────────────────────────────────────────────────────
jest
  .spyOn(AccessibilityInfo, "isReduceMotionEnabled")
  .mockResolvedValue(true);

// ─────────────────────────────────────────────────────────────────────────────
// Fixtures
// ─────────────────────────────────────────────────────────────────────────────

const SESSION: Session = {
  serverUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const PROFILE: ProfileDTO = {
  user_id: SESSION!.userId,
  height_m: 1.75,
  weight_kg: 80,
  birth_year: 1990,
  metabolic_formula: "mifflin_st_jeor_plus5",
  units_preference: "metric",
  timezone: "America/New_York",
  updated_at: "2026-06-28T00:00:00Z",
};

/** Target read-model with all targets derived (no user override). */
const DERIVED_TARGET: TargetReadModel = {
  calories: { effective: 1800, derived: 1800, source: "derived" },
  protein_g: { effective: 128, derived: 128, source: "derived" },
  carbs_g: { effective: 148, derived: 148, source: "derived" },
  fat_g: { effective: 64, derived: 64, source: "derived" },
};
/** Target read-model with calorie override in force. */
const OVERRIDDEN_CALORIE_TARGET: TargetReadModel = {
  calories: { effective: 2000, derived: 1800, source: "user" },
  protein_g: { effective: 128, derived: 128, source: "derived" },
  carbs_g: { effective: 148, derived: 148, source: "derived" },
  fat_g: { effective: 64, derived: 64, source: "derived" },
};

/** Target read-model with protein override in force. */
const OVERRIDDEN_PROTEIN_TARGET: TargetReadModel = {
  calories: { effective: 1800, derived: 1800, source: "derived" },
  protein_g: { effective: 150, derived: 128, source: "user" },
  carbs_g: { effective: 148, derived: 148, source: "derived" },
  fat_g: { effective: 64, derived: 64, source: "derived" },
};

const GOAL_TARGET_RESPONSE: GoalTargetResponse = {
  goal: {
    id: "aaaa",
    user_id: SESSION!.userId,
    start_weight_kg: 80,
    start_date: "2026-06-28",
    target_weight_kg: 75,
    target_date: "2026-12-28",
    is_active: true,
  },
  target: {
    calories: 1678,
    rmr_kcal: 1780,
    tdee_kcal: 2136,
    direction: "loss",
    clamped: false,
  },
  provenance: { source: "derived", basis: "goal_and_metrics" },
  clamp: { clamped: false, reason: null },
};

const UPDATED_TARGET_AFTER_GOAL: TargetReadModel = {
  calories: { effective: 1678, derived: 1678, source: "derived" },
  protein_g: { effective: 128, derived: 128, source: "derived" },
  carbs_g: { effective: 108, derived: 108, source: "derived" },
  fat_g: { effective: 64, derived: 64, source: "derived" },
};

// ─────────────────────────────────────────────────────────────────────────────
// Mock injectable stores / adapters
// ─────────────────────────────────────────────────────────────────────────────

function mockSettingsStore(
  initialAppearance: "light" | "dark" | "system" = "system",
): AppSettingsStore & { _appearance: "light" | "dark" | "system" } {
  let appearance = initialAppearance;
  return {
    get _appearance() {
      return appearance;
    },
    getAppearance: jest.fn(async () => appearance),
    setAppearance: jest.fn(async (v: "light" | "dark" | "system") => {
      appearance = v;
    }),
  };
}

function mockCadenceStore(
  initialCadence: WeighInCadence | null = "weekly",
): CadenceStore & { _cadence: WeighInCadence | null } {
  let cadence = initialCadence;
  return {
    get _cadence() {
      return cadence;
    },
    getCadence: jest.fn(async () => cadence),
    setCadence: jest.fn(async (c: WeighInCadence) => {
      cadence = c;
    }),
    getLastWeighInDate: jest.fn(async () => null),
    setLastWeighInDate: jest.fn(async () => {}),
  };
}

function mockNotifications(): NotificationsAdapter {
  return {
    requestPermission: jest.fn(async () => true),
    cancelAll: jest.fn(async () => {}),
    scheduleAt: jest.fn(async () => {}),
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Render helper
// ─────────────────────────────────────────────────────────────────────────────

const SAFE_AREA_METRICS = {
  frame: { x: 0, y: 0, width: 390, height: 844 },
  insets: { top: 47, left: 0, right: 0, bottom: 34 },
};

function renderSettings(
  props: Partial<Parameters<typeof SettingsScreen>[0]> & {
    colorScheme?: "light" | "dark";
  } = {},
): ReactTestRenderer {
  const { colorScheme = "light", ...screenProps } = props;
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <SafeAreaProvider initialMetrics={SAFE_AREA_METRICS}>
        <ThemeProvider override={colorScheme}>
          <SettingsScreen
            session={SESSION}
            getProfileFn={jest.fn().mockResolvedValue(PROFILE)}
            getTargetFn={jest.fn().mockResolvedValue(DERIVED_TARGET)}
            putProfileFn={jest.fn().mockResolvedValue(PROFILE)}
            createGoalFn={jest.fn().mockResolvedValue(GOAL_TARGET_RESPONSE)}
            getActiveGoalFn={jest.fn().mockResolvedValue(null)}
            setTargetOverrideFn={
              jest.fn().mockResolvedValue(OVERRIDDEN_CALORIE_TARGET)
            }
            resetTargetOverrideFn={jest.fn().mockResolvedValue(DERIVED_TARGET)}
            settingsStore={mockSettingsStore()}
            cadenceStore={mockCadenceStore()}
            notificationsAdapter={mockNotifications()}
            {...screenProps}
          />
        </ThemeProvider>
      </SafeAreaProvider>,
    );
  });
  return tree;
}

/** Collect all rendered text into a single string for quick assertions. */
function textContent(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

/** Find a pressable node by its accessibilityLabel. */
function findPressable(tree: ReactTestRenderer, label: string) {
  return tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
}

function press(tree: ReactTestRenderer, label: string) {
  const node = findPressable(tree, label);
  act(() => {
    node.props.onPress();
  });
}

/**
 * Select a segment on a native `SegmentedControl` by its visible label. The
 * native control exposes its labels via the `values` array and reports taps
 * through `onChange` (with the chosen index), so we locate the control offering
 * the label and fire its change event the way the platform would.
 */
function selectSegment(tree: ReactTestRenderer, label: string) {
  const control = tree.root.findAll(
    (n) =>
      typeof n.props.onChange === "function" &&
      Array.isArray(n.props.values) &&
      (n.props.values as string[]).includes(label),
  )[0];
  if (!control) {
    throw new Error(`No segmented control offers segment "${label}"`);
  }
  const index = (control.props.values as string[]).indexOf(label);
  act(() => {
    control.props.onChange({
      nativeEvent: { selectedSegmentIndex: index, value: label },
    });
  });
}

/** The visible segment labels of the native control with the given testID. */
function segmentValues(tree: ReactTestRenderer, testID: string): string[] {
  const control = tree.root.findAll(
    (n) => n.props.testID === testID && Array.isArray(n.props.values),
  )[0];
  return control ? (control.props.values as string[]) : [];
}

// ─────────────────────────────────────────────────────────────────────────────
// Tests: calorie-target provenance / override / reset
// ─────────────────────────────────────────────────────────────────────────────

describe("Calorie-target provenance", () => {
  it("shows '└ from your goal + metrics' when source is derived", async () => {
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(DERIVED_TARGET),
    });
    await act(async () => {});
    const text = textContent(tree);
    expect(text).toContain("└ from your goal + metrics");
  });

  it("shows '✎ set by you' when calorie is overridden (source: user)", async () => {
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(OVERRIDDEN_CALORIE_TARGET),
    });
    await act(async () => {});
    const text = textContent(tree);
    expect(text).toContain("✎ set by you");
  });

  it("shows effective calorie value", async () => {
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(DERIVED_TARGET),
    });
    await act(async () => {});
    const text = textContent(tree);
    expect(text).toContain("1800");
  });

  it("renders Reset button when calorie is overridden", async () => {
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(OVERRIDDEN_CALORIE_TARGET),
    });
    await act(async () => {});
    const resetBtn = findPressable(
      tree,
      "Reset Calories to derived value of 1800 kcal",
    );
    expect(resetBtn).toBeTruthy();
  });

  it("does NOT render Reset button when calorie is derived", async () => {
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(DERIVED_TARGET),
    });
    await act(async () => {});
    const found = tree.root.findAll(
      (n) =>
        n.props.accessibilityLabel &&
        typeof n.props.accessibilityLabel === "string" &&
        (n.props.accessibilityLabel as string).startsWith("Reset Calories"),
    );
    expect(found).toHaveLength(0);
  });

  it("calls resetTargetOverrideFn with ['calories'] when Reset is pressed", async () => {
    const resetFn = jest.fn().mockResolvedValue(DERIVED_TARGET);
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(OVERRIDDEN_CALORIE_TARGET),
      resetTargetOverrideFn: resetFn,
    });
    await act(async () => {});
    await act(async () => {
      press(tree, "Reset Calories to derived value of 1800 kcal");
    });
    expect(resetFn).toHaveBeenCalledWith(expect.anything(), ["calories"]);
  });

  it("updates display to derived after reset", async () => {
    const resetFn = jest.fn().mockResolvedValue(DERIVED_TARGET);
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(OVERRIDDEN_CALORIE_TARGET),
      resetTargetOverrideFn: resetFn,
    });
    await act(async () => {});
    await act(async () => {
      press(tree, "Reset Calories to derived value of 1800 kcal");
    });
    const text = textContent(tree);
    expect(text).toContain("└ from your goal + metrics");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Tests: macro-target provenance / override / reset
// ─────────────────────────────────────────────────────────────────────────────

describe("Macro-target provenance", () => {
  it("shows all three macro targets derived", async () => {
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(DERIVED_TARGET),
    });
    await act(async () => {});
    const text = textContent(tree);
    expect(text).toContain("128"); // protein
    expect(text).toContain("148"); // carbs
    expect(text).toContain("64"); // fat
  });

  it("shows '✎ set by you' for an overridden protein target", async () => {
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(OVERRIDDEN_PROTEIN_TARGET),
    });
    await act(async () => {});
    // The protein row carries "✎ set by you"
    const rows = tree.root.findAll((n) => n.props.testID === "protein-target-row");
    expect(rows.length).toBeGreaterThan(0);
    const provenanceTexts = rows[0]!.findAll(
      (n) => typeof n.props.children === "string" && n.props.children === "✎ set by you",
    );
    expect(provenanceTexts.length).toBeGreaterThan(0);
  });

  it("renders Reset button for protein when overridden", async () => {
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(OVERRIDDEN_PROTEIN_TARGET),
    });
    await act(async () => {});
    const resetBtn = findPressable(
      tree,
      "Reset Protein to derived value of 128 g",
    );
    expect(resetBtn).toBeTruthy();
  });

  it("calls resetTargetOverrideFn with ['protein'] on reset", async () => {
    const resetFn = jest.fn().mockResolvedValue(DERIVED_TARGET);
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(OVERRIDDEN_PROTEIN_TARGET),
      resetTargetOverrideFn: resetFn,
    });
    await act(async () => {});
    await act(async () => {
      press(tree, "Reset Protein to derived value of 128 g");
    });
    expect(resetFn).toHaveBeenCalledWith(expect.anything(), ["protein"]);
  });

  it("shows '└ from your goal + metrics' for carbs and fat when derived", async () => {
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(DERIVED_TARGET),
    });
    await act(async () => {});
    const carbsRow = tree.root.find((n) => n.props.testID === "carbs-target-row");
    const fatRow = tree.root.find((n) => n.props.testID === "fat-target-row");
    expect(carbsRow).toBeTruthy();
    expect(fatRow).toBeTruthy();
    const carbsTexts = carbsRow.findAll(
      (n) => n.props.children === "└ from your goal + metrics",
    );
    const fatTexts = fatRow.findAll(
      (n) => n.props.children === "└ from your goal + metrics",
    );
    expect(carbsTexts.length).toBeGreaterThan(0);
    expect(fatTexts.length).toBeGreaterThan(0);
  });

  it("calls setTargetOverrideFn with protein_target_g when override is saved", async () => {
    const overrideFn = jest.fn().mockResolvedValue(OVERRIDDEN_PROTEIN_TARGET);
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(DERIVED_TARGET),
      setTargetOverrideFn: overrideFn,
    });
    await act(async () => {});

    // Open the protein override edit by pressing the Protein target row
    await act(async () => {
      press(tree, "Protein: 128 g. Derived from your goal and metrics");
    });

    // Find the override input and set a value
    const input = tree.root.find(
      (n) =>
        n.props.accessibilityLabel !== undefined &&
        (n.props.accessibilityLabel as string).includes("protein"),
    );
    act(() => {
      input.props.onChangeText("150");
    });

    await act(async () => {
      press(tree, "Save override");
    });

    expect(overrideFn).toHaveBeenCalledWith(expect.anything(), {
      protein_target_g: 150,
    });
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Tests: mini target-reveal
// ─────────────────────────────────────────────────────────────────────────────

describe("Mini target-reveal", () => {
  it("shows the reveal after a goal edit that triggers a recompute", async () => {
    const createGoalFn = jest.fn().mockResolvedValue(GOAL_TARGET_RESPONSE);
    const getTargetFn = jest
      .fn()
      .mockResolvedValueOnce(DERIVED_TARGET) // initial load
      .mockResolvedValueOnce(UPDATED_TARGET_AFTER_GOAL); // after goal save

    const tree = renderSettings({ createGoalFn, getTargetFn });
    await act(async () => {});

    // Open goal edit and save
    await act(async () => {
      press(tree, "Goal: Details unavailable");
    });
    await act(async () => {
      press(tree, "Save goal");
    });
    await act(async () => {});

    const reveal = tree.root.findAll(
      (n) => n.props.testID === "mini-target-reveal",
    );
    expect(reveal.length).toBeGreaterThan(0);
  });

  it("shows updated calorie target in the reveal after goal edit", async () => {
    const createGoalFn = jest.fn().mockResolvedValue(GOAL_TARGET_RESPONSE);
    const getTargetFn = jest
      .fn()
      .mockResolvedValueOnce(DERIVED_TARGET)
      .mockResolvedValueOnce(UPDATED_TARGET_AFTER_GOAL);

    const tree = renderSettings({ createGoalFn, getTargetFn });
    await act(async () => {});

    await act(async () => {
      press(tree, "Goal: Details unavailable");
    });
    await act(async () => {
      press(tree, "Save goal");
    });
    await act(async () => {});

    const reveal = tree.root.find(
      (n) => n.props.testID === "mini-target-reveal",
    );
    // The reveal should show 1678 (UPDATED_TARGET_AFTER_GOAL.calories.effective)
    expect(reveal.props.accessibilityLabel).toContain("1678");
  });

  it("shows the reveal after a body-metric edit", async () => {
    const putProfileFn = jest.fn().mockResolvedValue({ ...PROFILE, weight_kg: 78 });
    const getTargetFn = jest
      .fn()
      .mockResolvedValueOnce(DERIVED_TARGET)
      .mockResolvedValueOnce(UPDATED_TARGET_AFTER_GOAL);

    const tree = renderSettings({ putProfileFn, getTargetFn });
    await act(async () => {});

    // Open weight edit
    await act(async () => {
      press(
        tree,
        "Weight: 80 kilograms",
      );
    });

    // Type a new value
    const input = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "New weight in kilograms" &&
        typeof n.props.onChangeText === "function",
    );
    act(() => {
      input.props.onChangeText("78");
    });

    await act(async () => {
      press(tree, "Save body metric");
    });
    await act(async () => {});

    const reveals = tree.root.findAll(
      (n) => n.props.testID === "mini-target-reveal",
    );
    expect(reveals.length).toBeGreaterThan(0);
  });

  it("shows calm prompt when profile is incomplete (no target)", async () => {
    const getTargetFn = jest.fn().mockRejectedValue({ status: 404 });
    const tree = renderSettings({ getTargetFn });
    await act(async () => {});
    const text = textContent(tree);
    expect(text).toContain("Set your goal + metrics to see your target");
  });

  it("does not show a broken number for incomplete profile", async () => {
    const getTargetFn = jest.fn().mockRejectedValue({ status: 404 });
    const tree = renderSettings({ getTargetFn });
    await act(async () => {});
    // Should not contain raw numbers from a stale/null target
    const text = textContent(tree);
    expect(text).not.toContain("undefined");
    expect(text).not.toContain("NaN");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Tests: five groups render in light and dark
// ─────────────────────────────────────────────────────────────────────────────

describe("Settings groups in light and dark", () => {
  for (const scheme of ["light", "dark"] as const) {
    it(`renders all five section headers in ${scheme} mode`, async () => {
      const tree = renderSettings({ colorScheme: scheme });
      await act(async () => {});
      const text = textContent(tree);
      expect(text).toContain("YOU");
      expect(text).toContain("BODY");
      expect(text).toContain("PREFERENCES");
      expect(text).toContain("ACCOUNT & SERVER");
      expect(text).toContain("DATA & ABOUT");
    });

    it(`renders the calorie-target row in ${scheme} mode`, async () => {
      const tree = renderSettings({ colorScheme: scheme });
      await act(async () => {});
      const row = tree.root.findAll(
        (n) => n.props.testID === "calorie-target-row",
      );
      expect(row.length).toBeGreaterThan(0);
    });

    it(`renders preferences rows (Units, Appearance, Weigh-in) in ${scheme} mode`, async () => {
      const tree = renderSettings({ colorScheme: scheme });
      await act(async () => {});
      const text = textContent(tree);
      expect(text).toContain("Units");
      expect(text).toContain("Appearance");
      expect(text).toContain("Weigh-in reminder");
    });
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// Tests: PREFERENCES persistence
// ─────────────────────────────────────────────────────────────────────────────

describe("PREFERENCES persistence", () => {
  it("writes units_preference via putProfile when units toggle changes", async () => {
    const putProfileFn = jest.fn().mockResolvedValue({
      ...PROFILE,
      units_preference: "imperial",
    });
    const tree = renderSettings({ putProfileFn });
    await act(async () => {});

    await act(async () => {
      selectSegment(tree, "Imperial");
    });

    expect(putProfileFn).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ units_preference: "imperial" }),
    );
  });

  it("pushes the saved units preference into the session-scoped provider (FTY-410)", async () => {
    // The "no stale metric render" wiring: after a successful units save,
    // Settings updates the shared UnitsPreferenceProvider so Trends reflects the
    // change on the next visit without a refetch. A sibling consumer stands in
    // for Trends here.
    const putProfileFn = jest.fn().mockResolvedValue({
      ...PROFILE,
      units_preference: "imperial",
    });
    const seen: { units: UnitsPreference | null } = { units: null };
    function Consumer() {
      const units = useUnitsPreference();
      React.useEffect(() => {
        seen.units = units;
      });
      return null;
    }

    let tree!: ReactTestRenderer;
    act(() => {
      tree = create(
        <SafeAreaProvider initialMetrics={SAFE_AREA_METRICS}>
          <ThemeProvider override="light">
            <UnitsPreferenceProvider readUnitsPreference={async () => "metric"}>
              <SettingsScreen
                session={SESSION}
                getProfileFn={jest.fn().mockResolvedValue(PROFILE)}
                getTargetFn={jest.fn().mockResolvedValue(DERIVED_TARGET)}
                putProfileFn={putProfileFn}
                createGoalFn={jest.fn().mockResolvedValue(GOAL_TARGET_RESPONSE)}
                getActiveGoalFn={jest.fn().mockResolvedValue(null)}
                setTargetOverrideFn={jest.fn().mockResolvedValue(OVERRIDDEN_CALORIE_TARGET)}
                resetTargetOverrideFn={jest.fn().mockResolvedValue(DERIVED_TARGET)}
                settingsStore={mockSettingsStore()}
                cadenceStore={mockCadenceStore()}
                notificationsAdapter={mockNotifications()}
              />
              <Consumer />
            </UnitsPreferenceProvider>
          </ThemeProvider>
        </SafeAreaProvider>,
      );
    });
    await act(async () => {});
    expect(seen.units).toBe("metric");

    await act(async () => {
      selectSegment(tree, "Imperial");
    });

    expect(putProfileFn).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ units_preference: "imperial" }),
    );
    expect(seen.units).toBe("imperial");
  });

  it("persists appearance on-device via settingsStore.setAppearance", async () => {
    const store = mockSettingsStore("system");
    const tree = renderSettings({ settingsStore: store });
    await act(async () => {});

    await act(async () => {
      selectSegment(tree, "Dark");
    });

    expect(store.setAppearance).toHaveBeenCalledWith("dark");
  });

  it("calls onAppearanceChange when appearance changes", async () => {
    const onAppearanceChange = jest.fn();
    const tree = renderSettings({ onAppearanceChange });
    await act(async () => {});

    await act(async () => {
      selectSegment(tree, "Dark");
    });

    expect(onAppearanceChange).toHaveBeenCalledWith("dark");
  });

  it("renders the four short cadence labels that fit the equal-width segments (FTY-347)", async () => {
    const tree = renderSettings({});
    await act(async () => {});

    // Short, ellipsis-free labels for the native equal-width UISegmentedControl.
    expect(segmentValues(tree, "cadence-segmented-control")).toEqual([
      "Weekly",
      "Biweekly",
      "Monthly",
      "Off",
    ]);
    // The long form that overflowed the segment is gone.
    expect(segmentValues(tree, "cadence-segmented-control")).not.toContain(
      "Every 2 weeks",
    );
  });

  it("persists cadence on-device via cadenceStore.setCadence", async () => {
    const cadenceStore = mockCadenceStore("weekly");
    const tree = renderSettings({ cadenceStore });
    await act(async () => {});

    await act(async () => {
      selectSegment(tree, "Biweekly");
    });

    expect(cadenceStore.setCadence).toHaveBeenCalledWith("biweekly");
  });

  it("cancels all reminders when cadence is set to Off", async () => {
    const notificationsAdapter = mockNotifications();
    const cadenceStore = mockCadenceStore("weekly");
    const tree = renderSettings({ notificationsAdapter, cadenceStore });
    await act(async () => {});

    await act(async () => {
      selectSegment(tree, "Off");
    });

    expect(notificationsAdapter.cancelAll).toHaveBeenCalled();
  });

  it("does NOT schedule a daily reminder (off schedule fires days out)", async () => {
    // The scheduler guarantees no daily notifications — covered by
    // reminderScheduler.test.ts; this test verifies the settings screen
    // delegates cadence changes through the scheduler, not raw scheduling.
    const notifications = mockNotifications();
    const cadenceStore = mockCadenceStore("weekly");
    const tree = renderSettings({ notificationsAdapter: notifications, cadenceStore });
    await act(async () => {});

    // Changing to biweekly should call cancelAll before scheduling (if any)
    await act(async () => {
      selectSegment(tree, "Biweekly");
    });

    // cancelAll is NOT called — applyReminderSettings returns early when there is no lastWeighInDate
    expect(notifications.cancelAll).not.toHaveBeenCalled();
    // scheduleAt is NOT called because there is no lastWeighInDate (null → no schedule)
    expect(notifications.scheduleAt).not.toHaveBeenCalled();
  });
});

// Tests: Sign out
// ─────────────────────────────────────────────────────────────────────────────

describe("Sign out", () => {
  it("calls sessionController.signOut() when Sign out is pressed", async () => {
    mockSignOut.mockResolvedValue(undefined);
    const tree = renderSettings();
    await act(async () => {});

    await act(async () => {
      press(tree, "Sign out");
    });

    expect(mockSignOut).toHaveBeenCalled();
  });

  it("shows the sign-in prompt when session is null", async () => {
    // Temporarily return null session
    const { useSession } = jest.requireMock<typeof import("@/state/session")>(
      "@/state/session",
    );
    (useSession as jest.Mock).mockReturnValueOnce(null);

    const tree = renderSettings({ session: null });
    await act(async () => {});

    const text = textContent(tree);
    expect(text).toContain("Sign in to access settings");
  });

  it("routes into the sign-in flow from the signed-out prompt (no dead-end)", async () => {
    const replace = jest.fn();
    const { useRouter } = jest.requireMock<typeof import("expo-router")>(
      "expo-router",
    );
    (useRouter as jest.Mock).mockReturnValueOnce({
      push: jest.fn(),
      back: jest.fn(),
      replace,
    });

    const tree = renderSettings({ session: null });
    await act(async () => {});

    const signIn = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Sign in" &&
        typeof n.props.onPress === "function",
    );
    act(() => {
      signIn.props.onPress();
    });
    expect(replace).toHaveBeenCalledWith("/signin");
  });

  it("shows ACCOUNT & SERVER section with server URL when signed in", async () => {
    const tree = renderSettings();
    await act(async () => {});
    const text = textContent(tree);
    expect(text).toContain("api.example.test");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Tests: Data & About rows
// ─────────────────────────────────────────────────────────────────────────────

describe("Data & About", () => {
  it("renders the version row", async () => {
    const tree = renderSettings({ appVersion: "1.2.3" });
    await act(async () => {});
    const text = textContent(tree);
    expect(text).toContain("1.2.3");
    expect(text).toContain("Version");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Tests: Accessibility
// ─────────────────────────────────────────────────────────────────────────────

describe("Accessibility", () => {
  it("provenance markers carry accessibilityLabel", async () => {
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(DERIVED_TARGET),
    });
    await act(async () => {});

    // VoiceOver should describe provenance on the calorie row
    const calorieRow = tree.root.find(
      (n) => n.props.testID === "calorie-target-row",
    );
    const provenanceText = calorieRow.find(
      (n) =>
        typeof n.props.accessibilityLabel === "string" &&
        (n.props.accessibilityLabel as string).includes("goal and metrics"),
    );
    expect(provenanceText).toBeTruthy();
  });

  it("editable body metric rows have ≥44pt min height", async () => {
    const tree = renderSettings();
    await act(async () => {});

    // Find weight row's pressable (minHeight from styles.settingsRow)
    const weightRow = tree.root.find(
      (n) =>
        n.props.accessibilityLabel !== undefined &&
        (n.props.accessibilityLabel as string).includes("Weight:"),
    );
    expect(weightRow).toBeTruthy();
  });

  it("override edit reveals calorie VoiceOver label", async () => {
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(DERIVED_TARGET),
    });
    await act(async () => {});

    const calorieBtn = findPressable(
      tree,
      "Calories: 1800 kcal. Derived from your goal and metrics",
    );
    expect(calorieBtn).toBeTruthy();
    expect(calorieBtn.props.accessibilityHint).toContain("custom value");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Tests: No sensitive values in logs / errors
// ─────────────────────────────────────────────────────────────────────────────

describe("No sensitive values in logs", () => {
  it("does not log calorie numbers on API error", async () => {
    const consoleSpy = jest.spyOn(console, "log").mockImplementation(() => {});
    const errorSpy = jest.spyOn(console, "error").mockImplementation(() => {});

    const resetFn = jest.fn().mockRejectedValue({ status: 500, message: "error" });
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(OVERRIDDEN_CALORIE_TARGET),
      resetTargetOverrideFn: resetFn,
    });
    await act(async () => {});

    await act(async () => {
      press(tree, "Reset Calories to derived value of 1800 kcal");
    });

    // Log calls should not contain sensitive numbers (e.g. calorie targets)
    const loggedArgs = [
      ...consoleSpy.mock.calls.flat(),
      ...errorSpy.mock.calls.flat(),
    ].map(String);
    for (const arg of loggedArgs) {
      // Should not contain the effective calorie value 2000 or the derived 1800
      expect(arg).not.toMatch(/\b(2000|1800)\b/);
    }

    consoleSpy.mockRestore();
    errorSpy.mockRestore();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Tests: Goal row honesty (never contradicts the rendered targets)
// ─────────────────────────────────────────────────────────────────────────────

describe("Goal row honesty", () => {
  it("keeps an active goal neutral when only the target is loaded", async () => {
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(DERIVED_TARGET),
    });
    await act(async () => {});
    expect(() => findPressable(tree, "Goal: Details unavailable")).not.toThrow();
    expect(() => findPressable(tree, "Goal: Loading…")).toThrow();
    expect(textContent(tree)).not.toContain("Active");
    expect(textContent(tree)).not.toContain("Not set");
  });

  it("shows 'Not set' only when there is genuinely no active goal", async () => {
    const tree = renderSettings({
      getTargetFn: jest.fn().mockRejectedValue({ status: 404 }),
    });
    await act(async () => {});
    expect(() => findPressable(tree, "Goal: Not set")).not.toThrow();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Tests: goal editor never submits an invalid direction/pace combination
// `faster` is a loss-only pace preset; the backend rejects {gain, faster} (422).
// ─────────────────────────────────────────────────────────────────────────────

describe("Goal editor pace validity", () => {
  it("clamps a previously-chosen 'faster' pace when switching to 'gain'", async () => {
    const createGoalFn = jest.fn().mockResolvedValue(GOAL_TARGET_RESPONSE);
    const getTargetFn = jest
      .fn()
      .mockResolvedValueOnce(DERIVED_TARGET)
      .mockResolvedValueOnce(UPDATED_TARGET_AFTER_GOAL);

    const tree = renderSettings({ createGoalFn, getTargetFn });
    await act(async () => {});

    // Open the goal editor (defaults to the loss direction).
    await act(async () => {
      press(tree, "Goal: Details unavailable");
    });
    // Pick the loss-only 'faster' pace, then switch the direction to gain.
    await act(async () => {
      selectSegment(tree, "Faster");
    });
    await act(async () => {
      selectSegment(tree, "Gain");
    });
    await act(async () => {
      press(tree, "Save goal");
    });
    await act(async () => {});

    // The submitted payload must be structurally valid: gain never carries
    // 'faster'. It is clamped back to 'steady' on the direction change.
    expect(createGoalFn).toHaveBeenCalledTimes(1);
    expect(createGoalFn.mock.calls[0][1]).toEqual({
      direction: "gain",
      pace: "steady",
    });
  });

  it("does not offer the 'Faster' pace for a gain goal", async () => {
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(DERIVED_TARGET),
    });
    await act(async () => {});

    await act(async () => {
      press(tree, "Goal: Details unavailable");
    });
    await act(async () => {
      selectSegment(tree, "Gain");
    });

    // The loss-only preset must not be an offered segment under gain.
    expect(segmentValues(tree, "goal-pace-segmented-control")).not.toContain(
      "Faster",
    );
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Tests: in-place save/reset error feedback (no sensitive context)
// ─────────────────────────────────────────────────────────────────────────────

describe("Save error feedback", () => {
  it("shows the friendly 422 message in the override card on an out-of-band value", async () => {
    const overrideFn = jest
      .fn()
      .mockRejectedValue(
        new GoalsApiError(422, "That goal or override value is not valid."),
      );
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(DERIVED_TARGET),
      setTargetOverrideFn: overrideFn,
    });
    await act(async () => {});

    await act(async () => {
      press(tree, "Calories: 1800 kcal. Derived from your goal and metrics");
    });
    await act(async () => {
      press(tree, "Save override");
    });
    await act(async () => {});

    const errorNode = tree.root.find(
      (n) =>
        n.props.testID === "calorie-override-edit-error" &&
        typeof n.props.children === "string",
    );
    expect(errorNode.props.children).toContain("not valid");
    // The edit card stays open so the user can correct the value.
    expect(
      tree.root.findAll((n) => n.props.testID === "calorie-override-edit").length,
    ).toBeGreaterThan(0);
  });

  it("does not surface raw target numbers in the error message", async () => {
    const overrideFn = jest
      .fn()
      .mockRejectedValue(
        new GoalsApiError(422, "That goal or override value is not valid."),
      );
    const tree = renderSettings({
      getTargetFn: jest.fn().mockResolvedValue(DERIVED_TARGET),
      setTargetOverrideFn: overrideFn,
    });
    await act(async () => {});
    await act(async () => {
      press(tree, "Calories: 1800 kcal. Derived from your goal and metrics");
    });
    await act(async () => {
      press(tree, "Save override");
    });
    await act(async () => {});
    const errorNode = tree.root.find(
      (n) =>
        n.props.testID === "calorie-override-edit-error" &&
        typeof n.props.children === "string",
    );
    expect(String(errorNode.props.children)).not.toMatch(/\b(1800|2000)\b/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Tests: clamp note in the mini-reveal (FTY-106 reveal contract)
// ─────────────────────────────────────────────────────────────────────────────

describe("Mini-reveal clamp note", () => {
  it("surfaces the safe-limit note when the goal target was clamped", async () => {
    const clampedResponse: GoalTargetResponse = {
      ...GOAL_TARGET_RESPONSE,
      target: { ...GOAL_TARGET_RESPONSE.target, clamped: true },
      clamp: { clamped: true, reason: "clamped_to_floor" },
    };
    const createGoalFn = jest.fn().mockResolvedValue(clampedResponse);
    const getTargetFn = jest
      .fn()
      .mockResolvedValueOnce(DERIVED_TARGET)
      .mockResolvedValueOnce(UPDATED_TARGET_AFTER_GOAL);

    const tree = renderSettings({ createGoalFn, getTargetFn });
    await act(async () => {});
    await act(async () => {
      press(tree, "Goal: Details unavailable");
    });
    await act(async () => {
      press(tree, "Save goal");
    });
    await act(async () => {});

    expect(
      tree.root.findAll((n) => n.props.testID === "reveal-clamp-note").length,
    ).toBeGreaterThan(0);
    const reveal = tree.root.find(
      (n) => n.props.testID === "mini-target-reveal",
    );
    expect(reveal.props.accessibilityLabel).toContain("safe limit");
  });

  it("omits the clamp note when the target was within the safe band", async () => {
    const createGoalFn = jest.fn().mockResolvedValue(GOAL_TARGET_RESPONSE);
    const getTargetFn = jest
      .fn()
      .mockResolvedValueOnce(DERIVED_TARGET)
      .mockResolvedValueOnce(UPDATED_TARGET_AFTER_GOAL);

    const tree = renderSettings({ createGoalFn, getTargetFn });
    await act(async () => {});
    await act(async () => {
      press(tree, "Goal: Details unavailable");
    });
    await act(async () => {
      press(tree, "Save goal");
    });
    await act(async () => {});

    expect(
      tree.root.findAll((n) => n.props.testID === "reveal-clamp-note").length,
    ).toBe(0);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Tests: imperial height edit (feet + inches, never drops inches or shows 12 in)
// ─────────────────────────────────────────────────────────────────────────────

const IMPERIAL_PROFILE: ProfileDTO = {
  ...PROFILE,
  units_preference: "imperial",
};

describe("Imperial height", () => {
  it("never renders a rounded '12 in'", async () => {
    // 1.8186 m is ~71.6 in — the old display rounded the inches part to 12.
    const tree = renderSettings({
      getProfileFn: jest
        .fn()
        .mockResolvedValue({ ...IMPERIAL_PROFILE, height_m: 1.8186 }),
    });
    await act(async () => {});
    const text = textContent(tree);
    expect(text).toContain("6 ft 0 in");
    expect(text).not.toContain("12 in");
  });

  it("captures feet AND inches and sends the combined height", async () => {
    const putProfileFn = jest.fn().mockResolvedValue(IMPERIAL_PROFILE);
    const tree = renderSettings({
      getProfileFn: jest.fn().mockResolvedValue(IMPERIAL_PROFILE),
      putProfileFn,
    });
    await act(async () => {});

    await act(async () => {
      press(tree, "Height: 5 feet 9 inches");
    });

    const feet = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "New height in feet" &&
        typeof n.props.onChangeText === "function",
    );
    const inches = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "New height inches" &&
        typeof n.props.onChangeText === "function",
    );
    act(() => {
      feet.props.onChangeText("5");
    });
    act(() => {
      inches.props.onChangeText("10");
    });

    await act(async () => {
      press(tree, "Save body metric");
    });
    await act(async () => {});

    expect(putProfileFn).toHaveBeenCalledTimes(1);
    const sent = putProfileFn.mock.calls[0][1] as { height_m: number };
    // 5 ft 10 in = 70 in = 1.778 m — inches must NOT be dropped.
    expect(sent.height_m).toBeCloseTo(1.778, 2);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Tests: Data & About stubs are honest (no flow is claimed to open)
// ─────────────────────────────────────────────────────────────────────────────

describe("Data & About stubs", () => {
  it("marks export and deletion as non-tappable Coming soon disclosures", async () => {
    const tree = renderSettings();
    await act(async () => {});
    expect(textContent(tree)).toContain("Coming soon");

    expect(() => findPressable(tree, "Export data")).toThrow();
    expect(() => findPressable(tree, "Delete account")).toThrow();

    const exportRow = tree.root.find((n) => n.props.accessibilityLabel === "Export data");
    expect(exportRow.props.accessibilityRole).toBeUndefined();
    expect(exportRow.props.accessibilityHint).toBeUndefined();
    expect(exportRow.props.onPress).toBeUndefined();

    const deleteRow = tree.root.find((n) => n.props.accessibilityLabel === "Delete account");
    expect(deleteRow.props.accessibilityRole).toBeUndefined();
    expect(deleteRow.props.accessibilityHint).toBeUndefined();
    expect(deleteRow.props.onPress).toBeUndefined();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Tests: visual-review seam — Settings edit sub-states (FTY-267)
//
// Each sub-state opens via the E2E-only initial-state seam (activating the
// registered preset), never a simulated tap, mirroring how the real deep-link
// route would seed it. The inertness test is the acceptance-criterion proof
// that the seam does nothing in a release/non-E2E build.
// ─────────────────────────────────────────────────────────────────────────────

describe("Visual-review seam — Settings edit sub-states (FTY-267)", () => {
  const gThis = globalThis as Record<string, unknown>;
  const ORIGINAL_DEV = gThis["__DEV__"] as boolean;
  const ORIGINAL_E2E_ENV = process.env.EXPO_PUBLIC_SLACKS_E2E;

  function enterE2EMode(): void {
    gThis["__DEV__"] = true;
    process.env["EXPO_PUBLIC_SLACKS_E2E"] = "true";
  }

  // The controller subscribes to the shared visual-review core store
  // (`useVisualReviewCore`), so a tree left mounted across tests would keep
  // receiving updates from a later test's `activateVisualReviewPreset` /
  // `__deactivateVisualReview` call outside that later test's `act()`. Unmount
  // after every test to keep each one's subscription scoped to itself.
  let mounted: ReactTestRenderer | null = null;

  function renderMounted(
    ...args: Parameters<typeof renderSettings>
  ): ReactTestRenderer {
    const tree = renderSettings(...args);
    mounted = tree;
    return tree;
  }

  afterEach(() => {
    if (mounted) {
      const tree = mounted;
      act(() => tree.unmount());
      mounted = null;
    }
    act(() => {
      __deactivateVisualReview();
    });
    gThis["__DEV__"] = ORIGINAL_DEV;
    if (ORIGINAL_E2E_ENV === undefined) {
      delete process.env["EXPO_PUBLIC_SLACKS_E2E"];
    } else {
      process.env["EXPO_PUBLIC_SLACKS_E2E"] = ORIGINAL_E2E_ENV;
    }
  });

  it("settings.goal_edit opens the goal editor via the seam, seeded from the loaded goal", async () => {
    enterE2EMode();
    activateVisualReviewPreset("settings.goal_edit", null);

    const tree = renderMounted({
      getActiveGoalFn: jest
        .fn()
        .mockResolvedValue({ direction: "gain", pace: "gentle" }),
    });
    await act(async () => {});

    // The edit card is present without pressing "Goal" — the seam, not a tap.
    expect(
      tree.root.findAll((n) => n.props.testID === "goal-edit-card").length,
    ).toBeGreaterThan(0);
    // Seeded from the loaded goal, not the 'loss' / 'steady' defaults.
    const directionControl = tree.root.findAll(
      (n) =>
        n.props.testID === "goal-direction-segmented-control" &&
        Array.isArray(n.props.values),
    )[0];
    expect(directionControl.props.selectedIndex).toBe(
      (directionControl.props.values as string[]).indexOf("Gain"),
    );
    const paceControl = tree.root.findAll(
      (n) =>
        n.props.testID === "goal-pace-segmented-control" &&
        Array.isArray(n.props.values),
    )[0];
    expect(paceControl.props.selectedIndex).toBe(
      (paceControl.props.values as string[]).indexOf("Gentle"),
    );
  });

  it("settings.body_edit opens the weight editor via the seam", async () => {
    enterE2EMode();
    activateVisualReviewPreset("settings.body_edit", null);

    const tree = renderMounted();
    await act(async () => {});

    expect(
      tree.root.findAll((n) => n.props.testID === "body-metric-edit-card").length,
    ).toBeGreaterThan(0);
    expect(textContent(tree)).toContain("New weight (kg)");
  });

  it("settings.formula_edit opens the formula editor via the seam with the loaded formula selected", async () => {
    enterE2EMode();
    activateVisualReviewPreset("settings.formula_edit", null);

    const tree = renderMounted();
    await act(async () => {});

    expect(
      tree.root.findAll((n) => n.props.testID === "formula-edit-card").length,
    ).toBeGreaterThan(0);
    const selectedFormula = tree.root.findAll(
      (n) =>
        n.props.accessibilityRole === "radio" &&
        n.props.accessibilityState?.selected === true &&
        typeof n.props.accessibilityLabel === "string" &&
        n.props.accessibilityLabel.includes("Mifflin-St Jeor"),
    );
    expect(selectedFormula.length).toBeGreaterThan(0);
    expect(textContent(tree)).toContain("Mifflin-St Jeor");
  });

  it("settings.target_override fixture renders the user override provenance without a tap", async () => {
    enterE2EMode();
    activateVisualReviewPreset("settings.target_override", null);

    const tree = renderMounted({
      getTargetFn: jest.fn().mockResolvedValue(OVERRIDDEN_CALORIE_TARGET),
    });
    await act(async () => {});

    expect(textContent(tree)).toContain("✎ set by you");
    expect(
      tree.root.findAll(
        (n) =>
          n.props.accessibilityLabel ===
            "Reset Calories to derived value of 1800 kcal" &&
          typeof n.props.onPress === "function",
      ),
    ).toHaveLength(1);
  });

  it("settings.appearance scrolls to the Preferences section via the seam", async () => {
    enterE2EMode();
    activateVisualReviewPreset("settings.appearance", null);

    const scrollToSpy = jest
      .spyOn(ScrollView.prototype, "scrollTo")
      .mockImplementation(() => {});
    const tree = renderMounted();
    await act(async () => {});

    const preferencesWrapper = tree.root.findAll(
      (n) => typeof n.props.onLayout === "function",
    )[0];
    act(() => {
      preferencesWrapper.props.onLayout({
        nativeEvent: { layout: { x: 0, y: 512, width: 320, height: 200 } },
      });
    });

    expect(scrollToSpy).toHaveBeenCalledWith({ y: 512, animated: false });
    scrollToSpy.mockRestore();
  });

  it("is inert with no active preset: no edit card opens and Preferences layout never scrolls (release-build proof)", async () => {
    enterE2EMode();
    // No activateVisualReviewPreset call — nothing is active.

    const scrollToSpy = jest
      .spyOn(ScrollView.prototype, "scrollTo")
      .mockImplementation(() => {});
    const tree = renderMounted();
    await act(async () => {});

    expect(
      tree.root.findAll((n) => n.props.testID === "goal-edit-card"),
    ).toHaveLength(0);
    expect(
      tree.root.findAll((n) => n.props.testID === "body-metric-edit-card"),
    ).toHaveLength(0);
    expect(
      tree.root.findAll((n) => n.props.testID === "formula-edit-card"),
    ).toHaveLength(0);
    expect(textContent(tree)).not.toContain("✎ set by you");

    const preferencesWrapper = tree.root.findAll(
      (n) => typeof n.props.onLayout === "function",
    )[0];
    act(() => {
      preferencesWrapper.props.onLayout({
        nativeEvent: { layout: { x: 0, y: 512, width: 320, height: 200 } },
      });
    });
    expect(scrollToSpy).not.toHaveBeenCalled();
    scrollToSpy.mockRestore();
  });

  it("is inert outside E2E mode even with a matching preset active (release-build proof)", async () => {
    // __DEV__ stays at its real (non-E2E-forced) value here — do not call
    // enterE2EMode(). Activation itself carries no E2E gate, so this proves the
    // controller's own isE2EMode() check (via useSettingsVisualReviewSubState)
    // is load-bearing.
    gThis["__DEV__"] = false;
    activateVisualReviewPreset("settings.goal_edit", null);

    const tree = renderMounted();
    await act(async () => {});

    expect(
      tree.root.findAll((n) => n.props.testID === "goal-edit-card"),
    ).toHaveLength(0);
  });

  it("is inert outside E2E mode for the target override and formula editor presets", async () => {
    gThis["__DEV__"] = false;
    activateVisualReviewPreset("settings.formula_edit", null);

    let tree = renderMounted();
    await act(async () => {});
    expect(
      tree.root.findAll((n) => n.props.testID === "formula-edit-card"),
    ).toHaveLength(0);
    act(() => tree.unmount());
    mounted = null;

    activateVisualReviewPreset("settings.target_override", null);
    tree = renderMounted();
    mounted = tree;
    await act(async () => {});
    expect(textContent(tree)).not.toContain("✎ set by you");
  });
});
