/**
 * Tests for the goal-led onboarding flow (FTY-103).
 *
 * Covers the review-focus concerns:
 * - Step-flow: three steps render in order; forward is gated on per-step
 *   validity; back navigation preserves entered values; maintain hides pace;
 *   the default pace is the steady option.
 * - Auto-detect: units default from a mocked locale; timezone from a mocked
 *   device IANA zone; both are shown read-only without prompting the user;
 *   metric and imperial locales each produce the correct canonical payload.
 * - Goal + measurement writes: step 1 sends createGoal with direction/pace;
 *   step 2 PUTs the canonical profile payload with a concrete formula variant.
 * - Target reveal: the reveal renders the target with the provenance line; a
 *   clamped response surfaces the calm clamp notice; "Get started" routes to
 *   Today.
 * - Accessibility: labelled controls, accessible stepper, ≥44pt targets, both
 *   colour schemes.
 * - Privacy: no profile, goal, or target value appears in logs.
 */

import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

jest.mock("expo-constants", () => ({
  __esModule: true,
  default: { get expoConfig() { return { extra: {} }; } },
}));

jest.mock("expo-secure-store", () => ({
  setItemAsync: async () => {},
  getItemAsync: async () => null,
  deleteItemAsync: async () => {},
}));

// expo-router is not available in the test environment; mock the router.
jest.mock("expo-router", () => ({
  useRouter: () => ({ replace: jest.fn() }),
  useSegments: () => [],
  useRootNavigationState: () => ({ key: "test-nav" }),
}));

// eslint-disable-next-line import/first
import { OnboardingScreen, type OnboardingScreenProps } from "./OnboardingScreen";
// eslint-disable-next-line import/first
import { ThemeProvider } from "@/theme";
// eslint-disable-next-line import/first
import type { SessionRecord } from "@/state/session";
// eslint-disable-next-line import/first
import { GoalsApiError, type GoalTargetResponse } from "@/api/goals";
// eslint-disable-next-line import/first
import type { ProfileDTO } from "@/api/profile";

// ─────────────────────────────────────────────────────────────────────────────
// Fixtures
// ─────────────────────────────────────────────────────────────────────────────

const SESSION: SessionRecord = {
  serverUrl: "https://home.example.net",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const GOAL_RESPONSE: GoalTargetResponse = {
  goal: {
    id: "g1",
    user_id: SESSION.userId,
    start_weight_kg: 80,
    start_date: "2026-06-01",
    target_weight_kg: 75,
    target_date: "2026-09-01",
    is_active: true,
  },
  target: {
    calories: 1900,
    rmr_kcal: 1600,
    tdee_kcal: 2200,
    direction: "loss",
    clamped: false,
  },
  provenance: { source: "derived", basis: "goal_and_metrics" },
  clamp: { clamped: false, reason: null },
};

const CLAMPED_GOAL_RESPONSE: GoalTargetResponse = {
  ...GOAL_RESPONSE,
  target: { ...GOAL_RESPONSE.target, calories: 1500, clamped: true },
  clamp: { clamped: true, reason: "below_minimum" },
};

const PROFILE_RESPONSE: ProfileDTO = {
  user_id: SESSION.userId,
  height_m: 1.75,
  weight_kg: 80,
  birth_year: 1990,
  metabolic_formula: "mifflin_st_jeor_plus5",
  units_preference: "metric",
  timezone: "UTC",
  updated_at: "2026-06-01T00:00:00Z",
};

// ─────────────────────────────────────────────────────────────────────────────
// Mount helper
// ─────────────────────────────────────────────────────────────────────────────

type Scheme = "light" | "dark";

async function mount(
  props: Partial<Omit<OnboardingScreenProps, "session">> & {
    scheme?: Scheme;
    session?: SessionRecord | null;
    createGoalFn?: jest.Mock;
    putProfileFn?: jest.Mock;
    detectUnitsFn?: jest.Mock;
    detectTimezoneFn?: jest.Mock;
    currentYearFn?: jest.Mock;
    onComplete?: jest.Mock;
  } = {},
): Promise<ReactTestRenderer> {
  const {
    scheme = "light",
    session = SESSION,
    createGoalFn = jest.fn(async () => GOAL_RESPONSE),
    putProfileFn = jest.fn(async () => PROFILE_RESPONSE),
    detectUnitsFn = jest.fn(() => "metric" as const),
    detectTimezoneFn = jest.fn(() => "Europe/London"),
    currentYearFn = jest.fn(() => 2026),
    onComplete = jest.fn(),
  } = props;

  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 390, height: 844 },
          insets: { top: 47, left: 0, right: 0, bottom: 34 },
        }}
      >
        <ThemeProvider override={scheme}>
          <OnboardingScreen
            session={session}
            createGoalFn={createGoalFn}
            putProfileFn={putProfileFn}
            detectUnitsFn={detectUnitsFn}
            detectTimezoneFn={detectTimezoneFn}
            currentYearFn={currentYearFn}
            onComplete={onComplete}
          />
        </ThemeProvider>
      </SafeAreaProvider>,
    );
    await new Promise((r) => setTimeout(r, 0));
  });
  return tree;
}

// ─────────────────────────────────────────────────────────────────────────────
// Query helpers
// ─────────────────────────────────────────────────────────────────────────────

function texts(tree: ReactTestRenderer): string[] {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string);
}

function byLabel(tree: ReactTestRenderer, label: string) {
  return tree.root.find((n) => n.props.accessibilityLabel === label);
}

function byTestId(tree: ReactTestRenderer, id: string) {
  return tree.root.find((n) => n.props.testID === id);
}

function radioGroup(tree: ReactTestRenderer, label: string) {
  return tree.root.find(
    (n) =>
      n.props.accessibilityRole === "radiogroup" &&
      n.props.accessibilityLabel === label,
  );
}

function selectedRadio(tree: ReactTestRenderer, groupLabel: string): string | null {
  const group = radioGroup(tree, groupLabel);
  const selected = group.findAll(
    (n) =>
      n.props.accessibilityRole === "radio" &&
      n.props.accessibilityState?.selected === true,
  );
  return selected[0]?.props.accessibilityLabel ?? null;
}

function pressRadio(tree: ReactTestRenderer, label: string): void {
  act(() => {
    byLabel(tree, label).props.onPress();
  });
}

async function pressGetStarted(tree: ReactTestRenderer): Promise<void> {
  await act(async () => {
    byLabel(tree, "Get started — go to Today").props.onPress();
    await new Promise((r) => setTimeout(r, 0));
  });
}

function fillField(tree: ReactTestRenderer, label: string, value: string): void {
  act(() => {
    byLabel(tree, label).props.onChangeText(value);
  });
}

function flattenStyle(style: unknown): Record<string, unknown> {
  if (Array.isArray(style)) {
    return style.reduce<Record<string, unknown>>(
      (acc, s) => ({ ...acc, ...flattenStyle(s) }),
      {},
    );
  }
  return (style as Record<string, unknown>) ?? {};
}

/** Fill in valid metric measurements (height in cm, weight in kg). */
async function fillMetricMeasurements(
  tree: ReactTestRenderer,
  formula: string = "Higher baseline (+5). Mifflin-St Jeor with the +5 constant — a higher resting estimate.",
): Promise<void> {
  fillField(tree, "Height (cm)", "175");
  fillField(tree, "Weight (kg)", "80");
  fillField(tree, "Birth year", "1990");
  act(() => { byLabel(tree, formula).props.onPress(); });
}

/** Fill in valid imperial measurements (height in ft/in, weight in lb). */
async function fillImperialMeasurements(tree: ReactTestRenderer): Promise<void> {
  fillField(tree, "Height feet", "5");
  fillField(tree, "Height inches", "9");
  fillField(tree, "Weight (lb)", "176");
  fillField(tree, "Birth year", "1990");
  act(() => {
    byLabel(
      tree,
      "Higher baseline (+5). Mifflin-St Jeor with the +5 constant — a higher resting estimate.",
    ).props.onPress();
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Step-flow tests
// ─────────────────────────────────────────────────────────────────────────────

describe("step-flow", () => {
  it("renders step 1 (goal + pace) by default", async () => {
    const tree = await mount();
    const t = texts(tree);
    expect(t).toContain("What's your goal?");
  });

  it("shows a progress stepper on step 1 with no back button", async () => {
    const tree = await mount();
    // On step 1 there is no back button (no previous step).
    const allButtons = tree.root.findAll(
      (n) =>
        n.props.accessibilityRole === "button" &&
        n.props.accessibilityLabel === "Back",
    );
    expect(allButtons).toHaveLength(0);
  });

  it("advances to step 2 on Continue (goal is valid)", async () => {
    const tree = await mount();
    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(texts(tree)).toContain("Your body metrics");
  });

  it("shows back button on step 2", async () => {
    const tree = await mount();
    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(byTestId(tree, "back-button")).toBeTruthy();
  });

  it("goes back to step 1 and preserves the direction selection", async () => {
    const tree = await mount();
    // Change direction to gain.
    pressRadio(tree, "Gain");
    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    // Now on step 2 — press back.
    act(() => { byTestId(tree, "back-button").props.onPress(); });
    // Back on step 1, direction should still be Gain.
    expect(
      selectedRadio(tree, "Goal direction"),
    ).toBe("Gain");
  });

  it("hides the pace control when maintain is selected", async () => {
    const tree = await mount();
    pressRadio(tree, "Maintain");
    expect(
      tree.root.findAll(
        (n) =>
          n.props.accessibilityRole === "radiogroup" &&
          n.props.accessibilityLabel === "Goal pace",
      ),
    ).toHaveLength(0);
  });

  it("shows pace options when lose is selected", async () => {
    const tree = await mount();
    pressRadio(tree, "Lose");
    expect(radioGroup(tree, "Goal pace")).toBeTruthy();
  });

  it("shows pace options when gain is selected", async () => {
    const tree = await mount();
    pressRadio(tree, "Gain");
    expect(radioGroup(tree, "Goal pace")).toBeTruthy();
  });

  it("defaults to the steady pace (evidence-based recommendation)", async () => {
    const tree = await mount();
    expect(selectedRadio(tree, "Goal pace")).toMatch(/Steady/);
  });

  it("advance to step 3 after completing step 2", async () => {
    const tree = await mount();
    // Step 1 → 2
    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    // Fill step 2
    await fillMetricMeasurements(tree);
    // Step 2 → 3
    await act(async () => {
      byLabel(tree, "Continue to your target").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(texts(tree)).toContain("Your daily target");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Auto-detect tests
// ─────────────────────────────────────────────────────────────────────────────

describe("auto-detect", () => {
  it("shows detected metric units read-only in step 2", async () => {
    const tree = await mount({ detectUnitsFn: jest.fn(() => "metric" as const) });
    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    const t = texts(tree);
    expect(t.some((s) => s.includes("Metric"))).toBe(true);
  });

  it("shows detected imperial units read-only in step 2", async () => {
    const tree = await mount({ detectUnitsFn: jest.fn(() => "imperial" as const) });
    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    const t = texts(tree);
    expect(t.some((s) => s.includes("Imperial"))).toBe(true);
  });

  it("shows detected timezone read-only in step 2", async () => {
    const tree = await mount({
      detectTimezoneFn: jest.fn(() => "America/Chicago"),
    });
    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    const t = texts(tree);
    expect(t.some((s) => s.includes("America/Chicago"))).toBe(true);
  });

  it("labels the auto-detect block with accessibility descriptions", async () => {
    const tree = await mount({
      detectUnitsFn: jest.fn(() => "metric" as const),
      detectTimezoneFn: jest.fn(() => "Europe/Berlin"),
    });
    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(
      byLabel(tree, "Units: Metric (auto-detected from your device)"),
    ).toBeTruthy();
    expect(
      byLabel(tree, "Timezone: Europe/Berlin (auto-detected from your device)"),
    ).toBeTruthy();
  });

  it("shows imperial height fields (ft + in) for an imperial locale", async () => {
    const tree = await mount({ detectUnitsFn: jest.fn(() => "imperial" as const) });
    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(byLabel(tree, "Height feet")).toBeTruthy();
    expect(byLabel(tree, "Height inches")).toBeTruthy();
  });

  it("shows a single cm height field for a metric locale", async () => {
    const tree = await mount({ detectUnitsFn: jest.fn(() => "metric" as const) });
    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    expect(byLabel(tree, "Height (cm)")).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Goal + measurement write tests
// ─────────────────────────────────────────────────────────────────────────────

describe("goal + measurement writes", () => {
  it("calls createGoal with the selected direction and pace (metric, loss + steady)", async () => {
    const createGoalFn = jest.fn(async () => GOAL_RESPONSE);
    const putProfileFn = jest.fn(async () => PROFILE_RESPONSE);
    const tree = await mount({ createGoalFn, putProfileFn });

    // Step 1: select loss + faster
    pressRadio(tree, "Faster: ~0.75–1% of bodyweight / week");

    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });

    // Step 2: fill and continue
    await fillMetricMeasurements(tree);
    await act(async () => {
      byLabel(tree, "Continue to your target").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(createGoalFn).toHaveBeenCalledWith(
      expect.objectContaining({ baseUrl: SESSION.serverUrl, userId: SESSION.userId }),
      { direction: "loss", pace: "faster" },
    );
  });

  it("calls createGoal without pace when direction is maintain", async () => {
    const createGoalFn = jest.fn(async () => GOAL_RESPONSE);
    const putProfileFn = jest.fn(async () => PROFILE_RESPONSE);
    const tree = await mount({ createGoalFn, putProfileFn });

    pressRadio(tree, "Maintain");
    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    await fillMetricMeasurements(tree);
    await act(async () => {
      byLabel(tree, "Continue to your target").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(createGoalFn).toHaveBeenCalledWith(
      expect.anything(),
      { direction: "maintain" },
    );
    const goalCallArgs = createGoalFn.mock.calls[0] as unknown[];
    expect(goalCallArgs[1]).not.toHaveProperty("pace");
  });

  it("PUTs the canonical metric payload with a concrete formula variant (never the placeholder)", async () => {
    const createGoalFn = jest.fn(async () => GOAL_RESPONSE);
    const putProfileFn = jest.fn(async () => PROFILE_RESPONSE);
    const tree = await mount({ createGoalFn, putProfileFn });

    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    await fillMetricMeasurements(tree);
    await act(async () => {
      byLabel(tree, "Continue to your target").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });

    const profileCallArgs = putProfileFn.mock.calls[0] as unknown[];
    const payload = profileCallArgs[1] as Record<string, unknown>;
    // Canonical units: metres for height, kg for weight.
    expect(typeof payload.height_m).toBe("number");
    expect(typeof payload.weight_kg).toBe("number");
    expect(typeof payload.birth_year).toBe("number");
    // Must be a concrete variant, not the family placeholder.
    expect(payload.metabolic_formula).toMatch(
      /^mifflin_st_jeor_(plus5|minus161)$/,
    );
  });

  it("PUTs the canonical imperial payload converted to metric units", async () => {
    const createGoalFn = jest.fn(async () => GOAL_RESPONSE);
    const putProfileFn = jest.fn(async () => PROFILE_RESPONSE);
    const tree = await mount({
      createGoalFn,
      putProfileFn,
      detectUnitsFn: jest.fn(() => "imperial" as const),
    });

    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    await fillImperialMeasurements(tree);
    await act(async () => {
      byLabel(tree, "Continue to your target").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });

    const profileCallArgs = putProfileFn.mock.calls[0] as unknown[];
    const payload = profileCallArgs[1] as Record<string, unknown>;
    // 5 ft 9 in → ~1.7526 m; 176 lb → ~79.8 kg
    expect(payload.height_m).toBeCloseTo(1.7526, 2);
    expect(payload.weight_kg).toBeCloseTo(79.832, 1);
    expect(payload.units_preference).toBe("imperial");
  });

  it("writes the auto-detected timezone into the profile payload", async () => {
    const createGoalFn = jest.fn(async () => GOAL_RESPONSE);
    const putProfileFn = jest.fn(async () => PROFILE_RESPONSE);
    const tree = await mount({
      createGoalFn,
      putProfileFn,
      detectTimezoneFn: jest.fn(() => "Asia/Tokyo"),
    });

    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    await fillMetricMeasurements(tree);
    await act(async () => {
      byLabel(tree, "Continue to your target").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });

    const profileCallArgs = putProfileFn.mock.calls[0] as unknown[];
    const payload = profileCallArgs[1] as Record<string, unknown>;
    expect(payload.timezone).toBe("Asia/Tokyo");
  });

  it("blocks Continue on step 2 and shows validation errors when fields are empty", async () => {
    const createGoalFn = jest.fn(async () => GOAL_RESPONSE);
    const tree = await mount({ createGoalFn });

    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    // Don't fill anything — just press continue.
    await act(async () => {
      byLabel(tree, "Continue to your target").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });

    // Should still be on step 2 (validation errors shown).
    expect(texts(tree)).toContain("Your body metrics");
    expect(createGoalFn).not.toHaveBeenCalled();
  });

  it("does not allow the unspecified formula placeholder to pass validation", async () => {
    const createGoalFn = jest.fn(async () => GOAL_RESPONSE);
    const putProfileFn = jest.fn(async () => PROFILE_RESPONSE);
    const tree = await mount({ createGoalFn, putProfileFn });

    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    // Fill all fields EXCEPT the formula.
    fillField(tree, "Height (cm)", "175");
    fillField(tree, "Weight (kg)", "80");
    fillField(tree, "Birth year", "1990");
    // Attempt to continue without selecting a formula.
    await act(async () => {
      byLabel(tree, "Continue to your target").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(texts(tree)).toContain("Your body metrics"); // still on step 2
    expect(createGoalFn).not.toHaveBeenCalled();
    expect(putProfileFn).not.toHaveBeenCalled();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Target reveal tests
// ─────────────────────────────────────────────────────────────────────────────

describe("target reveal", () => {
  async function advanceToReveal(
    tree: ReactTestRenderer,
    goalResponse = GOAL_RESPONSE,
  ): Promise<void> {
    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    await fillMetricMeasurements(tree);
    await act(async () => {
      byLabel(tree, "Continue to your target").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
  }

  it("renders the calorie target in the reveal hero", async () => {
    const tree = await mount({ createGoalFn: jest.fn(async () => GOAL_RESPONSE) });
    await advanceToReveal(tree);
    const hero = byTestId(tree, "reveal-hero");
    expect(hero.props.accessibilityLabel).toContain("1900");
  });

  it("renders the provenance line on the reveal", async () => {
    const tree = await mount({ createGoalFn: jest.fn(async () => GOAL_RESPONSE) });
    await advanceToReveal(tree);
    expect(byTestId(tree, "provenance-line")).toBeTruthy();
    const t = texts(tree);
    expect(t.some((s) => s.includes("from your goal"))).toBe(true);
  });

  it("does NOT show the clamp notice for an unclamped response", async () => {
    const tree = await mount({ createGoalFn: jest.fn(async () => GOAL_RESPONSE) });
    await advanceToReveal(tree);
    expect(
      tree.root.findAll((n) => n.props.testID === "clamp-notice"),
    ).toHaveLength(0);
  });

  it("surfaces the clamp notice for a clamped response", async () => {
    const tree = await mount({
      createGoalFn: jest.fn(async () => CLAMPED_GOAL_RESPONSE),
    });
    await advanceToReveal(tree, CLAMPED_GOAL_RESPONSE);
    expect(byTestId(tree, "clamp-notice")).toBeTruthy();
  });

  it("calls onComplete when the user presses Get started", async () => {
    const onComplete = jest.fn();
    const tree = await mount({ onComplete });
    await advanceToReveal(tree);
    await pressGetStarted(tree);
    expect(onComplete).toHaveBeenCalled();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Accessibility tests
// ─────────────────────────────────────────────────────────────────────────────

describe("accessibility", () => {
  it("labels the goal direction radio group", async () => {
    const tree = await mount();
    expect(radioGroup(tree, "Goal direction")).toBeTruthy();
  });

  it("labels the goal pace radio group", async () => {
    const tree = await mount();
    expect(radioGroup(tree, "Goal pace")).toBeTruthy();
  });

  it("stepper has progressbar role with correct value", async () => {
    const tree = await mount();
    const stepper = tree.root.find(
      (n) => n.props.accessibilityRole === "progressbar",
    );
    expect(stepper.props.accessibilityValue).toEqual({ now: 1, min: 1, max: 3 });
  });

  it("stepper advances to step 2 in accessibilityValue after Continue", async () => {
    const tree = await mount();
    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    const stepper = tree.root.find(
      (n) => n.props.accessibilityRole === "progressbar",
    );
    expect(stepper.props.accessibilityValue).toEqual({ now: 2, min: 1, max: 3 });
  });

  it("Continue button has ≥44pt touch target on step 1", async () => {
    const tree = await mount();
    // Find the pressable button by role + label.
    const btn = tree.root.find(
      (n) =>
        n.props.accessibilityRole === "button" &&
        n.props.accessibilityLabel === "Continue to measurements",
    );
    expect(flattenStyle(btn.props.style).minHeight).toBe(44);
  });

  it("renders with the dark colour palette without errors", async () => {
    const tree = await mount({ scheme: "dark" });
    // Just verify it mounts without throwing.
    expect(texts(tree)).toContain("What's your goal?");
  });

  it("labels the step 2 measurements header as a header role", async () => {
    const tree = await mount();
    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    const header = tree.root.find(
      (n) =>
        n.props.accessibilityRole === "header" &&
        n.props.children === "Your body metrics",
    );
    expect(header).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Privacy: no sensitive value in logs
// ─────────────────────────────────────────────────────────────────────────────

describe("privacy", () => {
  it("never writes profile, goal, or target values to logs", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map(
      (level) => jest.spyOn(console, level).mockImplementation(() => {}),
    );
    try {
      const tree = await mount({
        createGoalFn: jest.fn(async () => GOAL_RESPONSE),
        putProfileFn: jest.fn(async () => PROFILE_RESPONSE),
      });
      // Step 1 → 2
      await act(async () => {
        byLabel(tree, "Continue to measurements").props.onPress();
        await new Promise((r) => setTimeout(r, 0));
      });
      // Fill step 2
      await fillMetricMeasurements(tree);
      // Step 2 → 3
      await act(async () => {
        byLabel(tree, "Continue to your target").props.onPress();
        await new Promise((r) => setTimeout(r, 0));
      });

      const sensitiveValues = ["1900", "80", "1.75", "1990", SESSION.token];
      for (const spy of spies) {
        for (const call of spy.mock.calls) {
          const line = call.map((c) => String(c)).join(" ");
          for (const val of sensitiveValues) {
            expect(line).not.toContain(val);
          }
        }
      }
    } finally {
      spies.forEach((spy) => spy.mockRestore());
    }
  });
});

describe("save error handling", () => {
  it("surfaces the API error message when the goal save fails", async () => {
    // createGoal rejects with a GoalsApiError → errorMessage() returns its
    // message, which renders in the save-error alert. The user stays on step 2.
    const putProfileFn = jest.fn(async () => PROFILE_RESPONSE);
    const createGoalFn = jest.fn(async () => {
      throw new GoalsApiError(409, "That goal conflicts with an existing one.");
    });
    const tree = await mount({ createGoalFn, putProfileFn });

    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    await fillMetricMeasurements(tree);
    await act(async () => {
      byLabel(tree, "Continue to your target").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(createGoalFn).toHaveBeenCalled();
    expect(byTestId(tree, "save-error").props.children).toBe(
      "That goal conflicts with an existing one.",
    );
    // Stayed on step 2 (no reveal) — the failed save did not advance the flow.
    expect(texts(tree)).not.toContain("Your daily target");
  });

  it("shows a generic fallback message for a non-API (network) failure", async () => {
    // A plain Error (e.g. a network drop) → the generic, status-free fallback;
    // never a stack/body leak.
    const putProfileFn = jest.fn(async () => PROFILE_RESPONSE);
    const createGoalFn = jest.fn(async () => {
      throw new Error("network down");
    });
    const tree = await mount({ createGoalFn, putProfileFn });

    await act(async () => {
      byLabel(tree, "Continue to measurements").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });
    await fillMetricMeasurements(tree);
    await act(async () => {
      byLabel(tree, "Continue to your target").props.onPress();
      await new Promise((r) => setTimeout(r, 0));
    });

    expect(byTestId(tree, "save-error").props.children).toBe(
      "Could not save. Check your connection and try again.",
    );
  });
});
