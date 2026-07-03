import React from "react";
import { AccessibilityInfo } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import type { TargetReadModel } from "@/api/dailySummary";
import type { GoalTargetResponse } from "@/api/goals";
import type { ProfileDTO } from "@/api/profile";
import type { AppSettingsStore } from "@/state/appSettings";
import type {
  CadenceStore,
  NotificationsAdapter,
  WeighInCadence,
} from "@/state/reminderScheduler";
import type { Session } from "@/state/session";
import { ThemeProvider } from "@/theme";
import { SettingsScreen } from "./SettingsScreen";

jest.mock("expo-router", () => ({
  useRouter: jest.fn(() => ({
    push: jest.fn(),
    back: jest.fn(),
    replace: jest.fn(),
  })),
}));

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
      signOut: jest.fn(),
      signIn: jest.fn(),
      createAccount: jest.fn(),
    })),
  };
});

jest
  .spyOn(AccessibilityInfo, "isReduceMotionEnabled")
  .mockResolvedValue(true);

const SESSION: Session = {
  serverUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const PROFILE: ProfileDTO = {
  user_id: SESSION.userId,
  height_m: 1.75,
  weight_kg: 80,
  birth_year: 1990,
  metabolic_formula: "mifflin_st_jeor_plus5",
  units_preference: "metric",
  timezone: "America/New_York",
  updated_at: "2026-06-28T00:00:00Z",
};

const DERIVED_TARGET: TargetReadModel = {
  calories: { effective: 1800, derived: 1800, source: "derived" },
  protein_g: { effective: 128, derived: 128, source: "derived" },
  carbs_g: { effective: 148, derived: 148, source: "derived" },
  fat_g: { effective: 64, derived: 64, source: "derived" },
};

const ACTIVE_GOAL_SUMMARY = { direction: "loss" as const, pace: "steady" as const };

const GOAL_TARGET_RESPONSE: GoalTargetResponse = {
  goal: {
    id: "aaaa",
    user_id: SESSION.userId,
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

const SAFE_AREA_METRICS = {
  frame: { x: 0, y: 0, width: 390, height: 844 },
  insets: { top: 47, left: 0, right: 0, bottom: 34 },
};

function mockSettingsStore(): AppSettingsStore {
  return {
    getAppearance: jest.fn(async () => "system"),
    setAppearance: jest.fn(async () => {}),
  };
}

function mockCadenceStore(): CadenceStore {
  return {
    getCadence: jest.fn(async () => "weekly" as WeighInCadence),
    setCadence: jest.fn(async () => {}),
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

function renderSettings(
  props: Partial<Parameters<typeof SettingsScreen>[0]> = {},
): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <SafeAreaProvider initialMetrics={SAFE_AREA_METRICS}>
        <ThemeProvider override="light">
          <SettingsScreen
            session={SESSION}
            getProfileFn={jest.fn().mockResolvedValue(PROFILE)}
            getTargetFn={jest.fn().mockResolvedValue(DERIVED_TARGET)}
            getActiveGoalSummaryFn={jest.fn().mockResolvedValue(ACTIVE_GOAL_SUMMARY)}
            putProfileFn={jest.fn().mockResolvedValue(PROFILE)}
            createGoalFn={jest.fn().mockResolvedValue(GOAL_TARGET_RESPONSE)}
            settingsStore={mockSettingsStore()}
            cadenceStore={mockCadenceStore()}
            notificationsAdapter={mockNotifications()}
            {...props}
          />
        </ThemeProvider>
      </SafeAreaProvider>,
    );
  });
  return tree;
}

function textContent(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

function findPressable(tree: ReactTestRenderer, label: string) {
  return tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
}

function findPressableMatching(tree: ReactTestRenderer, pattern: RegExp) {
  return tree.root.find(
    (n) =>
      typeof n.props.accessibilityLabel === "string" &&
      pattern.test(n.props.accessibilityLabel) &&
      typeof n.props.onPress === "function",
  );
}

function press(tree: ReactTestRenderer, label: string) {
  act(() => {
    findPressable(tree, label).props.onPress();
  });
}

describe("SettingsScreen FTY-190 copy and affordances", () => {
  it("summarizes the loaded active goal with direction and pace", async () => {
    const getActiveGoalSummaryFn = jest.fn().mockResolvedValue(ACTIVE_GOAL_SUMMARY);
    const tree = renderSettings({ getActiveGoalSummaryFn });
    await act(async () => {});

    expect(getActiveGoalSummaryFn).toHaveBeenCalledTimes(1);
    expect(() => findPressable(tree, "Goal: Lose · Steady")).not.toThrow();
    expect(() => findPressable(tree, "Goal: Loading…")).toThrow();
    expect(textContent(tree)).not.toContain("Active");
  });

  it("renders export and delete account as non-tappable coming-soon disclosures", async () => {
    const tree = renderSettings();
    await act(async () => {});

    expect(textContent(tree)).toContain("Export data");
    expect(textContent(tree)).toContain("Delete account");
    expect(textContent(tree)).toContain("Coming soon");
    expect(() => findPressable(tree, "Export data")).toThrow();
    expect(() => findPressable(tree, "Delete account")).toThrow();
  });

  it("keeps visible labels associated with units and appearance segments", async () => {
    const tree = renderSettings();
    await act(async () => {});

    expect(textContent(tree)).toContain("Units");
    expect(textContent(tree)).toContain("Appearance");
    expect(tree.root.find((n) => n.props.accessibilityLabel === "Units preference")).toBeTruthy();
    expect(tree.root.find((n) => n.props.accessibilityLabel === "Appearance")).toBeTruthy();
  });

  it("explains calculation preference plainly without changing saved values", async () => {
    const putProfileFn = jest.fn().mockResolvedValue({
      ...PROFILE,
      metabolic_formula: "mifflin_st_jeor_minus161",
    });
    const tree = renderSettings({ putProfileFn });
    await act(async () => {});

    expect(textContent(tree)).toContain("Higher calorie baseline");
    expect(textContent(tree)).not.toContain("Higher baseline (+5)");

    await act(async () => {
      findPressableMatching(tree, /^Calculation preference:/).props.onPress();
    });

    expect(textContent(tree)).toContain("Uses the Mifflin-St Jeor +5 baseline");
    expect(textContent(tree)).toContain("Uses the Mifflin-St Jeor -161 baseline");

    await act(async () => {
      press(
        tree,
        "Lower calorie baseline. Uses the Mifflin-St Jeor -161 baseline, giving a lower resting burn estimate.",
      );
    });
    await act(async () => {
      press(tree, "Save calculation preference");
    });

    expect(putProfileFn).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ metabolic_formula: "mifflin_st_jeor_minus161" }),
    );
  });
});
