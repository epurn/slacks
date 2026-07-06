import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { StyleSheet, View } from "react-native";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { floatingSwitcherClearance } from "@/components/ui";

import { TrendsScreen } from "./TrendsScreen";
import {
  WeightApiError,
  type WeightEntryDTO,
} from "@/api/weightEntries";
import { DailySummaryApiError } from "@/api/dailySummary";
import type { DailySummaryDTO, TargetReadModel } from "@/api/dailySummary";
import { useVisualReviewCore } from "@/e2e/visualReview/hooks";
import { SessionProvider, type Session, type SessionRecord } from "@/state/session";
import type { SessionStore } from "@/state/sessionStore";
import { GoalDirectionProvider } from "@/state/goalDirection";
import type { GoalDirection } from "@/api/goals";
import type { CadenceStore, NotificationsAdapter, WeighInCadence } from "@/state/reminderScheduler";
import {
  DATE_RANGE_OPTIONS,
  rangeProse,
  type DateRangeKey,
} from "@/state/trends";
import { formatDate } from "@/state/weightEntries";
import { ThemeProvider, lightPalette, darkPalette, typeScale } from "@/theme";

// The visual-review `weight.sheet` seam (FTY-265) tests below stub just
// `useVisualReviewCore` so they can control the "active preset" TrendsScreen
// reads without touching the real singleton registry/session — a shared,
// stateful module many *other* tests in this file mount against and never
// explicitly unmount, so driving the real activate/deactivate would notify
// those long-lived trees' store subscriptions outside `act()`. Other hooks
// pass through their real implementation.
jest.mock("@/e2e/visualReview/hooks", () => ({
  ...jest.requireActual("@/e2e/visualReview/hooks"),
  useVisualReviewCore: jest.fn(
    jest.requireActual("@/e2e/visualReview/hooks").useVisualReviewCore,
  ),
}));

// TrendsScreen now uses ScreenHeader → AppIcon (expo-symbols); stub the native
// module so tests run without a native runtime.
jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require("react");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require("react-native");
  return {
    SymbolView: ({ name, accessibilityLabel }: { name: string; accessibilityLabel?: string }) =>
      React.createElement(View, { testID: `sf-symbol-${String(name)}`, accessibilityLabel }),
  };
});

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

const SESSION: Session = {
  serverUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const NOW = new Date("2026-06-27T12:00:00Z");

function makeEntry(
  id: string,
  weight_kg: number,
  date: string,
): WeightEntryDTO {
  return {
    id,
    user_id: SESSION!.userId,
    weight_kg,
    effective_date: date,
    created_at: `${date}T08:00:00Z`,
    updated_at: `${date}T08:00:00Z`,
  };
}

function makeTarget(calories: number): TargetReadModel {
  return {
    calories: { effective: calories, derived: calories, source: "derived" },
    protein_g: { effective: 128, derived: 128, source: "derived" },
    carbs_g: { effective: 148, derived: 148, source: "derived" },
    fat_g: { effective: 64, derived: 64, source: "derived" },
  };
}

function makeSummary(
  date: string,
  intake: number,
  targetCal: number | null,
  hasIntake = true,
  uncountedEntries = 0,
): DailySummaryDTO {
  return {
    date,
    intake: { calories: intake, protein_g: 80, carbs_g: 150, fat_g: 40 },
    has_intake: hasIntake,
    uncounted_entries: uncountedEntries,
    target: targetCal !== null ? makeTarget(targetCal) : null,
    exercise: { active_calories: 0 },
  };
}

/** A session store that hydrates the signed-in SESSION for the live-path test. */
function sessionStore(): SessionStore {
  let value: SessionRecord | null = { ...SESSION! };
  return {
    load: async () => value,
    save: async (s: SessionRecord) => {
      value = s;
    },
    clear: async () => {
      value = null;
    },
  } satisfies SessionStore;
}

function mockStore(
  cadence: WeighInCadence = "weekly",
): CadenceStore {
  let storedCadence: WeighInCadence = cadence;
  let storedDate: string | null = null;
  return {
    getCadence: async () => storedCadence,
    setCadence: async (c) => { storedCadence = c; },
    getLastWeighInDate: async () => storedDate,
    setLastWeighInDate: async (d) => { storedDate = d; },
  };
}

function mockNotifications(): NotificationsAdapter & { scheduled: Date[] } {
  const scheduled: Date[] = [];
  return {
    scheduled,
    requestPermission: async () => true,
    cancelAll: async () => {},
    scheduleAt: async (d) => { scheduled.push(d); },
  };
}

function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 390, height: 844 },
          insets: { top: 47, left: 0, right: 0, bottom: 34 },
        }}
      >
        {element}
      </SafeAreaProvider>,
    );
  });
  return tree;
}

/**
 * The native range `SegmentedControl` node (carries `values` + `onChange`).
 * Several host layers share the props; the first is enough to read/drive.
 */
function findRangeSelector(tree: ReactTestRenderer) {
  return tree.root.findAll(
    (n) =>
      n.props.testID === "trends-range-selector" &&
      typeof n.props.onChange === "function" &&
      Array.isArray(n.props.values),
  )[0];
}

/** Drive the native range control to the given range key, as a tap would. */
function selectRange(tree: ReactTestRenderer, key: DateRangeKey) {
  const control = findRangeSelector(tree);
  if (!control) {
    throw new Error("range selector not found");
  }
  const index = DATE_RANGE_OPTIONS.findIndex((o) => o.key === key);
  act(() => {
    control.props.onChange({
      nativeEvent: {
        selectedSegmentIndex: index,
        value: (control.props.values as string[])[index],
      },
    });
  });
}

function textContent(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

async function waitForAssertion(assertion: () => void) {
  let lastError: unknown;
  for (let attempt = 0; attempt < 5; attempt++) {
    await act(async () => { await Promise.resolve(); });
    try {
      assertion();
      return;
    } catch (err: unknown) {
      lastError = err;
    }
  }
  throw lastError;
}

async function waitForAdherenceSettled(tree: ReactTestRenderer) {
  await waitForAssertion(() => {
    expect(tree.root.findAll((n) => n.props.testID === "adherence-loading")).toHaveLength(0);
  });
}

async function waitForSheetSettled(tree: ReactTestRenderer) {
  await waitForAssertion(() => {
    expect(tree.root.findAll((n) =>
      String(n.props.accessibilityLabel).startsWith("Weight in"),
    ).length).toBeGreaterThan(0);
  });
}

/** The headline delta `Text` node (e.g. " ↓0.4 this month"). */
function findHeadlineDeltaNode(tree: ReactTestRenderer) {
  return tree.root.findAll(
    (n) =>
      (n.type as unknown) === "Text" &&
      typeof n.props.children === "string" &&
      /[↑↓→]/.test(n.props.children as string),
  )[0];
}

/** The resolved `color` style of a rendered node (style is `[base, {color}]`). */
function styleColor(node: { props: { style?: unknown } }): string | undefined {
  const style = node.props.style;
  const arr = Array.isArray(style) ? style : [style];
  const withColor = arr.find(
    (s): s is { color: string } =>
      typeof s === "object" && s !== null && "color" in s,
  );
  return withColor?.color;
}

/** The strip cell's fill `View` (index 1: index 0 is the 44×44 tap-target wrapper). */
function findCellFillNode(tree: ReactTestRenderer, date: string) {
  const cell = tree.root.find((n) => n.props.testID === `adherence-cell-${date}`);
  return cell.findAllByType(View)[1]!;
}

describe("TrendsScreen — no session", () => {
  it("shows a sign-in message when no session is present", () => {
    const list = jest.fn();
    const tree = mount(
      <TrendsScreen
        session={null}
        listWeightEntries={list}
        getDailySummaryRange={jest.fn()}
        now={NOW}
      />,
    );
    expect(textContent(tree)).toContain("Sign in to view your trends");
    expect(list).not.toHaveBeenCalled();
  });
});

describe("TrendsScreen — weight entries", () => {
  it("shows loading state while entries are fetching", async () => {
    const list = jest.fn().mockReturnValue(new Promise(() => {}));
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={list}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    const loading = tree.root.find(
      (n) => n.props.accessibilityLabel === "Loading weight trend",
    );
    expect(loading).toBeTruthy();
    await waitForAdherenceSettled(tree);
  });

  it("loads entries for the selected range (1M default = 30 days)", async () => {
    const list = jest.fn().mockResolvedValue([]);
    mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={list}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    await act(async () => {});
    expect(list).toHaveBeenCalledTimes(1);
    const [, from, to] = list.mock.calls[0] as [unknown, string, string];
    expect(to).toBe("2026-06-27");
    expect(from).toBe("2026-05-28"); // 30 days before June 27
  });

  it("shows error state and retry button when load fails", async () => {
    const list = jest.fn().mockRejectedValue(
      new WeightApiError(500, "Could not load your weight trend."),
    );
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={list}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    await act(async () => {});
    const alert = tree.root.find((n) => n.props.accessibilityRole === "alert");
    expect(alert).toBeTruthy();
    const retry = tree.root.find(
      (n) => n.props.accessibilityLabel === "Try again",
    );
    expect(retry).toBeTruthy();
  });

  it("shows the empty invite when no entries exist", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    await act(async () => {});
    expect(textContent(tree)).toContain("Log your first weigh-in");
  });
});

describe("TrendsScreen — range selector", () => {
  it("renders a native range control offering 1M, 3M, 6M", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    await act(async () => {});
    const control = findRangeSelector(tree);
    expect(control).toBeTruthy();
    // The native control's segment labels, in order, are the three range labels.
    expect(control.props.values).toEqual(
      DATE_RANGE_OPTIONS.map((o) => o.label),
    );
  });

  it("switching range re-fetches both weight entries and adherence data", async () => {
    const list = jest.fn().mockResolvedValue([]);
    const getSum = jest.fn().mockResolvedValue([
      makeSummary("2026-06-27", 2000, 2000),
    ]);
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={list}
        getDailySummaryRange={getSum}
        now={NOW}
      />,
    );
    await act(async () => {});

    const initialListCalls = list.mock.calls.length;
    const initialSumCalls = getSum.mock.calls.length;

    // Switch to 3M
    selectRange(tree, "3M");
    await act(async () => {});

    expect(list.mock.calls.length).toBeGreaterThan(initialListCalls);
    expect(getSum.mock.calls.length).toBeGreaterThan(initialSumCalls);
  });

  it("switching to 3M fetches entries from 90 days before today", async () => {
    const list = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={list}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    await act(async () => {});

    selectRange(tree, "3M");
    await act(async () => {});

    const lastCall = list.mock.calls[list.mock.calls.length - 1] as [
      unknown,
      string,
      string,
    ];
    expect(lastCall[1]).toBe("2026-03-29"); // 90 days before June 27
    expect(lastCall[2]).toBe("2026-06-27");
  });
});

describe("TrendsScreen — headline delta", () => {
  it("shows headline delta with direction when entries exist", async () => {
    const entries = [
      makeEntry("1", 72, "2026-06-01"),
      makeEntry("2", 70, "2026-06-20"),
    ];
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue(entries)}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
        unitsPreference="metric"
      />,
    );
    await act(async () => {});
    const content = textContent(tree);
    // Should show a delta direction
    expect(content).toMatch(/[↑↓→]/);
  });

  it("renders the current-value headline through the display face (tabular-nums, per typeScale.title1)", async () => {
    const entries = [
      makeEntry("1", 72, "2026-06-01"),
      makeEntry("2", 70, "2026-06-20"),
    ];
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue(entries)}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
        unitsPreference="metric"
      />,
    );
    await act(async () => {});
    // Scope to the headline row (its accessibilityLabel starts with "Current
    // weight trend:") so this doesn't collide with the chart's own axis-label
    // Text nodes, which also end in the unit string.
    const headlineRow = tree.root.find(
      (n) =>
        typeof n.props.accessibilityLabel === "string" &&
        (n.props.accessibilityLabel as string).startsWith("Current weight trend:"),
    );
    const valueNode = headlineRow.findAll(
      (n) => (n.type as unknown as string) === "Text",
    )[0]!;
    const styles: Array<Record<string, unknown>> = Array.isArray(valueNode.props.style)
      ? valueNode.props.style
      : [valueNode.props.style];
    const combined = Object.assign({}, ...styles);
    expect(combined.fontVariant).toEqual(["tabular-nums"]);
    expect(combined.fontSize).toBe(typeScale.title1);
  });
});

describe("TrendsScreen — adherence summary", () => {
  it("shows avg kcal and days-on-target when summaries are available", async () => {
    const getSum = jest.fn().mockResolvedValue([
      makeSummary("2026-06-27", 2000, 2000),
    ]);
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={getSum}
        now={NOW}
      />,
    );
    await act(async () => {});
    const content = textContent(tree);
    expect(content).toContain("kcal");
  });

  it("null-target days appear in the adherence strip with a distinct 'no target' label", async () => {
    const getSum = jest.fn().mockResolvedValue([
      makeSummary("2026-06-27", 0, null),
    ]);
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={getSum}
        now={NOW}
      />,
    );
    await act(async () => {});
    // At least one cell should have "no target set" in its accessibility label
    const cells = tree.root.findAll(
      (n) =>
        typeof n.props.accessibilityLabel === "string" &&
        (n.props.accessibilityLabel as string).includes("no target"),
    );
    expect(cells.length).toBeGreaterThan(0);
  });
});

describe("TrendsScreen — past-day drilldown", () => {
  it("calls onDayPress with the tapped date when a strip cell is pressed", async () => {
    const onDayPress = jest.fn();
    const getSum = jest.fn().mockResolvedValue([
      makeSummary("2026-06-27", 2000, 2000),
    ]);
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={getSum}
        now={NOW}
        onDayPress={onDayPress}
      />,
    );
    await act(async () => {});

    // Find any adherence cell
    const cells = tree.root.findAll(
      (n) =>
        typeof n.props.testID === "string" &&
        (n.props.testID as string).startsWith("adherence-cell-"),
    );
    expect(cells.length).toBeGreaterThan(0);

    act(() => {
      cells[0]!.props.onPress();
    });
    expect(onDayPress).toHaveBeenCalledTimes(1);
    // The date argument should match the cell's date
    const pressedDate = onDayPress.mock.calls[0]?.[0] as string;
    expect(pressedDate).toMatch(/^\d{4}-\d{2}-\d{2}$/);
  });
});

describe("TrendsScreen — log weight sheet", () => {
  it("opens the log-weight sheet when '+ Log weight' is pressed", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    await act(async () => {});

    const logBtn = tree.root.find(
      (n) => n.props.accessibilityLabel === "Log weight",
    );
    act(() => logBtn.props.onPress());
    await waitForSheetSettled(tree);

    // The native sheet presents: its content (the weight field) is now mounted.
    const inputs = tree.root.findAll((n) =>
      String(n.props.accessibilityLabel).startsWith("Weight in"),
    );
    expect(inputs.length).toBeGreaterThan(0);
  });

  it("re-fetches entries after a successful save to show the new point", async () => {
    const list = jest.fn().mockResolvedValue([]);
    const createEntry = jest.fn().mockResolvedValue(makeEntry("1", 70, "2026-06-27"));
    const store = mockStore();
    const notifications = mockNotifications();

    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={list}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        createWeightEntry={createEntry}
        store={store}
        notifications={notifications}
        now={NOW}
      />,
    );
    await act(async () => {});

    const callsBeforeSave = list.mock.calls.length;

    // Open sheet
    const logBtn = tree.root.find(
      (n) => n.props.accessibilityLabel === "Log weight",
    );
    act(() => logBtn.props.onPress());
    await waitForSheetSettled(tree);

    // Find the weight input and enter a value
    const input = tree.root.find(
      (n) =>
        typeof n.props.accessibilityLabel === "string" &&
        (n.props.accessibilityLabel as string).startsWith("Weight in"),
    );
    act(() => input.props.onChangeText("70"));

    // Submit
    const submitBtn = tree.root.findAll(
      (n) => n.props.accessibilityLabel === "Log weight" && typeof n.props.onPress === "function",
    );
    // Use the last one (the one in the sheet)
    await act(async () => {
      submitBtn[submitBtn.length - 1]!.props.onPress();
    });

    expect(list.mock.calls.length).toBeGreaterThan(callsBeforeSave);
  });

  it("sends the weight in user display units and converts to kg at the API boundary via the create endpoint", async () => {
    const list = jest.fn().mockResolvedValue([]);
    const createEntry = jest.fn().mockResolvedValue(makeEntry("1", 70, "2026-06-27"));

    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={list}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        createWeightEntry={createEntry}
        now={NOW}
        unitsPreference="metric"
      />,
    );
    await act(async () => {});

    // Open sheet
    const logBtn = tree.root.find(
      (n) => n.props.accessibilityLabel === "Log weight",
    );
    act(() => logBtn.props.onPress());
    await waitForSheetSettled(tree);

    const input = tree.root.find(
      (n) =>
        typeof n.props.accessibilityLabel === "string" &&
        (n.props.accessibilityLabel as string).startsWith("Weight in"),
    );
    act(() => input.props.onChangeText("70"));

    const submitBtns = tree.root.findAll(
      (n) => n.props.accessibilityLabel === "Log weight" && typeof n.props.onPress === "function",
    );
    await act(async () => {
      submitBtns[submitBtns.length - 1]!.props.onPress();
    });

    expect(createEntry).toHaveBeenCalledTimes(1);
    const [, weight, date] = createEntry.mock.calls[0] as [unknown, number, string];
    expect(weight).toBe(70);
    expect(date).toBe("2026-06-27");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Visual-review `weight.sheet` seam (FTY-265): an E2E-only initial-state seam
// reaches the weight-log sheet's open sub-state without a simulated tap, and is
// proven inert outside E2E mode.
// ─────────────────────────────────────────────────────────────────────────────

describe("TrendsScreen — visual-review weight.sheet seam (FTY-265)", () => {
  const gThis = globalThis as Record<string, unknown>;
  const ORIGINAL_DEV = gThis["__DEV__"] as boolean;
  const ORIGINAL_E2E_ENV = process.env.EXPO_PUBLIC_FATTY_E2E;

  function setE2E(on: boolean): void {
    gThis["__DEV__"] = on;
    if (on) {
      process.env["EXPO_PUBLIC_FATTY_E2E"] = "true";
    } else {
      delete process.env["EXPO_PUBLIC_FATTY_E2E"];
    }
  }

  // Stubs the active-preset snapshot TrendsScreen reads via `useVisualReviewCore()`
  // — never the real singleton registry/session (shared, stateful module-level
  // state many other tests in this file mount against and never explicitly
  // unmount). Driving the *real* activate/deactivate here would notify those
  // long-lived, never-unmounted trees' store subscriptions outside `act()`.
  function mockActivePreset(presetName: string | null): void {
    (useVisualReviewCore as jest.Mock).mockReturnValue({
      presetName,
      route: presetName ? "/trends" : null,
      settledPath: presetName ? "/trends" : null,
      theme: null,
      signedOut: false,
      revision: 1,
    });
  }

  afterEach(() => {
    jest.restoreAllMocks();
    gThis["__DEV__"] = ORIGINAL_DEV;
    if (ORIGINAL_E2E_ENV === undefined) {
      delete process.env["EXPO_PUBLIC_FATTY_E2E"];
    } else {
      process.env["EXPO_PUBLIC_FATTY_E2E"] = ORIGINAL_E2E_ENV;
    }
  });

  it("opens the weight-log sheet on mount when weight.sheet is the active preset in E2E mode", async () => {
    setE2E(true);
    mockActivePreset("weight.sheet");

    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );

    // No "+ Log weight" press — the sheet is open purely from the initial-state
    // seam reflecting the already-active preset.
    await waitForSheetSettled(tree);
    expect(tree.root.findAll((n) => n.props.testID === "weight-log-sheet").length).toBeGreaterThan(0);
  });

  it("stays closed on mount outside E2E mode, even with weight.sheet marked active (release inertness)", async () => {
    setE2E(false);
    mockActivePreset("weight.sheet");

    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    await act(async () => {});

    expect(tree.root.findAll((n) => n.props.testID === "weight-log-sheet")).toHaveLength(0);
  });

  it("stays closed on mount in E2E mode when no preset (or a different preset) is active", async () => {
    setE2E(true);
    mockActivePreset(null);

    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    await act(async () => {});

    expect(tree.root.findAll((n) => n.props.testID === "weight-log-sheet")).toHaveLength(0);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Cadence card removed from Trends (FTY-187): weigh-in cadence is reachable
// only via Profile → Preferences; Trends must render no cadence controls.
// Logging a weight still persists the last-weigh-in date via `onWeightLogged`
// (verified above in "re-fetches entries after a successful save"), since
// Preferences' own cadence control reads that date to reschedule the reminder.
// ─────────────────────────────────────────────────────────────────────────────

describe("TrendsScreen — cadence card removed", () => {
  it("renders no cadence option controls", async () => {
    const store = mockStore();
    const notifications = mockNotifications();
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        store={store}
        notifications={notifications}
        now={NOW}
      />,
    );
    await act(async () => {});

    const cadenceOpts = tree.root.findAll(
      (n) =>
        typeof n.props.testID === "string" &&
        (n.props.testID as string).startsWith("cadence-option-"),
    );
    expect(cadenceOpts).toHaveLength(0);
    expect(textContent(tree)).not.toContain("WEIGH-IN REMINDER");
  });
});

describe("TrendsScreen — adherence fan-out removal", () => {
  it("issues exactly one range request for a multi-day range (not one per day)", async () => {
    const getSum = jest.fn().mockResolvedValue([]);
    mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={getSum}
        now={NOW}
      />,
    );
    await act(async () => {});
    // 1M default = 30 days; exactly one range call — not 30 per-day calls
    expect(getSum).toHaveBeenCalledTimes(1);
  });

  it("range switch issues exactly one new range request, not one per day", async () => {
    const getSum = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={getSum}
        now={NOW}
      />,
    );
    await act(async () => {});
    expect(getSum).toHaveBeenCalledTimes(1); // initial 1M load

    selectRange(tree, "3M");
    await act(async () => {});

    // One more call for the 3M range — not 90 per-day calls
    expect(getSum).toHaveBeenCalledTimes(2);
  });

  it("range switch passes the updated from/to to getDailySummaryRange", async () => {
    const getSum = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={getSum}
        now={NOW}
      />,
    );
    await act(async () => {});

    selectRange(tree, "3M");
    await act(async () => {});

    const lastCall = getSum.mock.calls[getSum.mock.calls.length - 1] as [
      unknown,
      string,
      string,
    ];
    expect(lastCall[1]).toBe("2026-03-29"); // 90 days before June 27
    expect(lastCall[2]).toBe("2026-06-27");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Adherence error / empty states (FTY-124)
// ─────────────────────────────────────────────────────────────────────────────

describe("TrendsScreen — adherence error and empty states", () => {
  it("failed range request shows an error surface with retry", async () => {
    const getSum = jest.fn().mockRejectedValue(
      new DailySummaryApiError(500, "Could not load your intake history. Please try again."),
    );
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={getSum}
        now={NOW}
      />,
    );
    await act(async () => {});

    const alert = tree.root.find((n) => n.props.accessibilityRole === "alert");
    expect(alert).toBeTruthy();
    // The error state carries its own screen-reader label, distinct from the
    // loading/empty/uncounted labels (FTY-188).
    expect(alert.props.accessibilityLabel).toBe(
      "Intake adherence failed to load",
    );

    const retry = tree.root.findAll(
      (n) => n.props.accessibilityLabel === "Try again",
    );
    expect(retry.length).toBeGreaterThan(0);
  });

  it("renders the retry label with the AA-safe accentText token in both palettes (FTY-209)", async () => {
    // The retry label is normal-size text on the raised surface, so it must use
    // the AA-safe `accentText` token, not the decorative `accent` (which fails
    // WCAG AA at ~2.14:1 on the light surface).
    for (const scheme of ["light", "dark"] as const) {
      const palette = scheme === "light" ? lightPalette : darkPalette;
      const tree = mount(
        <ThemeProvider override={scheme}>
          <TrendsScreen
            session={SESSION}
            listWeightEntries={jest.fn().mockResolvedValue([])}
            getDailySummaryRange={jest.fn().mockRejectedValue(
              new DailySummaryApiError(500, "error"),
            )}
            now={NOW}
          />
        </ThemeProvider>,
      );
      await act(async () => {});

      const retryLabel = tree.root.find(
        (n) =>
          (n.type as unknown as string) === "Text" &&
          n.props.children === "Try again",
      );
      expect(styleColor(retryLabel)).toBe(palette.accentText);
    }
    // The swap only matters on the light surface, where the tokens differ
    // (dark's accent is already AA-safe, so accentText aliases it there).
    expect(lightPalette.accentText).not.toBe(lightPalette.accent);
  });

  it("failed range request does not block the weight panel", async () => {
    const getSum = jest.fn().mockRejectedValue(
      new DailySummaryApiError(500, "error"),
    );
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([makeEntry("1", 70, "2026-06-27")])}
        getDailySummaryRange={getSum}
        now={NOW}
      />,
    );
    await act(async () => {});

    // Log weight button from the weight panel must still be present
    const logBtn = tree.root.find(
      (n) => n.props.accessibilityLabel === "Log weight",
    );
    expect(logBtn).toBeTruthy();
  });

  it("retry button re-fetches the range after an adherence error", async () => {
    let calls = 0;
    const getSum = jest.fn().mockImplementation(() => {
      calls++;
      if (calls === 1) {
        return Promise.reject(new DailySummaryApiError(500, "error"));
      }
      return Promise.resolve([makeSummary("2026-06-27", 2000, 2000)]);
    });

    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={getSum}
        now={NOW}
      />,
    );
    await act(async () => {});
    expect(getSum).toHaveBeenCalledTimes(1);

    const retry = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Try again" &&
        typeof n.props.onPress === "function",
    );
    await act(async () => retry.props.onPress());

    expect(getSum).toHaveBeenCalledTimes(2);
  });

  it("empty range (no summaries returned) shows the honest empty invite", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([])}
        now={NOW}
      />,
    );
    await act(async () => {});
    const content = textContent(tree);
    expect(content).toContain("No meals logged in this range yet");
    // The old lie must be gone.
    expect(content).not.toContain("No intake data");
    // Distinct screen-reader label for the empty state.
    expect(
      tree.root.findAll(
        (n) => n.props.accessibilityLabel === "No intake logged for this range",
      ).length,
    ).toBeGreaterThan(0);
  });

  it("422 from range maps to the DailySummaryApiError message (no personal data leaked)", async () => {
    const getSum = jest.fn().mockRejectedValue(
      new DailySummaryApiError(422, "Invalid date format."),
    );
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={getSum}
        now={NOW}
      />,
    );
    await act(async () => {});

    const content = textContent(tree);
    expect(content).toContain("Invalid date format.");
    // No numeric nutrition data in the error
    expect(content).not.toMatch(/\d{4}\s*kcal/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Adherence honesty — empty / uncounted / loading→resolves (FTY-188)
// ─────────────────────────────────────────────────────────────────────────────

describe("TrendsScreen — adherence honesty (FTY-188)", () => {
  /** The `to` bound of the default 1M range is today (NOW), so a summary on this
   * date lands inside the fetched window. */
  const TODAY = formatDate(NOW);

  it("uncounted range shows 'N entries awaiting details', never 'No intake data'", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest
          .fn()
          .mockResolvedValue([makeSummary(TODAY, 0, null, false, 3)])}
        now={NOW}
      />,
    );
    await act(async () => {});

    const content = textContent(tree);
    expect(content).toContain("3 entries awaiting details");
    // The two lies the card used to tell must both be absent.
    expect(content).not.toContain("No intake data");
    expect(content).not.toContain("No meals logged");
    // Distinct screen-reader label for the uncounted state.
    expect(
      tree.root.findAll(
        (n) => n.props.accessibilityLabel === "3 entries awaiting details",
      ).length,
    ).toBeGreaterThan(0);
  });

  it("a single uncounted entry uses the singular noun", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest
          .fn()
          .mockResolvedValue([makeSummary(TODAY, 0, null, false, 1)])}
        now={NOW}
      />,
    );
    await act(async () => {});
    expect(textContent(tree)).toContain("1 entry awaiting details");
  });

  it("counted data present alongside uncounted entries shows the data summary, not the awaiting copy", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest
          .fn()
          .mockResolvedValue([
            makeSummary(TODAY, 2000, 2000, true, 2),
          ])}
        now={NOW}
      />,
    );
    await act(async () => {});
    const content = textContent(tree);
    expect(content).toContain("Avg 2000 kcal/day");
    expect(content).not.toContain("awaiting details");
  });

  it("loading placeholder shows, then always resolves — empty range leaves no permanent skeleton", async () => {
    let resolveRange!: (v: DailySummaryDTO[]) => void;
    const pending = new Promise<DailySummaryDTO[]>((r) => {
      resolveRange = r;
    });
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockReturnValue(pending)}
        now={NOW}
      />,
    );
    // Flush the weight list + Skeleton's async Reduce-Motion check; the range
    // read is still pending, so adherence stays in the loading phase.
    await act(async () => {});

    // While the read is in flight, the loading placeholder is on screen.
    const loading = tree.root.find(
      (n) => n.props.testID === "adherence-loading",
    );
    expect(loading.props.accessibilityLabel).toBe("Loading intake adherence");

    // Resolve the read → the placeholder must be replaced by a real state.
    await act(async () => {
      resolveRange([]);
    });

    expect(
      tree.root.findAll((n) => n.props.testID === "adherence-loading").length,
    ).toBe(0);
    expect(textContent(tree)).toContain("No meals logged in this range yet");
  });

  it("loading placeholder resolves to the uncounted state too (no never-filling skeleton)", async () => {
    let resolveRange!: (v: DailySummaryDTO[]) => void;
    const pending = new Promise<DailySummaryDTO[]>((r) => {
      resolveRange = r;
    });
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockReturnValue(pending)}
        now={NOW}
      />,
    );
    await act(async () => {});
    expect(
      tree.root.findAll((n) => n.props.testID === "adherence-loading").length,
    ).toBeGreaterThan(0);

    await act(async () => {
      resolveRange([makeSummary(TODAY, 0, null, false, 2)]);
    });

    expect(
      tree.root.findAll((n) => n.props.testID === "adherence-loading").length,
    ).toBe(0);
    expect(textContent(tree)).toContain("2 entries awaiting details");
  });

  it("changing the range re-shows the loading placeholder, then resolves to the new range's state", async () => {
    let resolveSecond!: (v: DailySummaryDTO[]) => void;
    const getSum = jest
      .fn()
      .mockResolvedValueOnce([makeSummary(TODAY, 2000, 2000, true, 0)])
      .mockReturnValueOnce(
        new Promise<DailySummaryDTO[]>((r) => {
          resolveSecond = r;
        }),
      );
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={getSum}
        now={NOW}
      />,
    );
    await act(async () => {});

    // First read settled: real data on screen, no skeleton.
    expect(textContent(tree)).toContain("Avg 2000 kcal/day");
    expect(
      tree.root.findAll((n) => n.props.testID === "adherence-loading").length,
    ).toBe(0);

    // Switch range: the new read is in flight, so the stale ready content must
    // be replaced by the loading placeholder — not left on screen.
    selectRange(tree, "3M");
    await act(async () => {});
    expect(
      tree.root.findAll((n) => n.props.testID === "adherence-loading").length,
    ).toBeGreaterThan(0);
    expect(textContent(tree)).not.toContain("Avg 2000 kcal/day");

    // The new read settles: the placeholder resolves to the new range's state.
    await act(async () => {
      resolveSecond([]);
    });
    expect(
      tree.root.findAll((n) => n.props.testID === "adherence-loading").length,
    ).toBe(0);
    expect(textContent(tree)).toContain("No meals logged in this range yet");
  });

  it("changing the range after an adherence error re-shows the loading placeholder, not the stale error", async () => {
    const getSum = jest
      .fn()
      .mockRejectedValueOnce(new DailySummaryApiError(500, "boom"))
      .mockReturnValueOnce(new Promise<DailySummaryDTO[]>(() => {}));
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={getSum}
        now={NOW}
      />,
    );
    await act(async () => {});
    expect(
      tree.root.findAll((n) => n.props.accessibilityRole === "alert").length,
    ).toBeGreaterThan(0);

    selectRange(tree, "3M");
    await act(async () => {});

    expect(
      tree.root.findAll((n) => n.props.testID === "adherence-loading").length,
    ).toBeGreaterThan(0);
    expect(
      tree.root.findAll((n) => n.props.accessibilityRole === "alert").length,
    ).toBe(0);

    // The read is intentionally left pending; unmount so the skeleton's
    // animation loop doesn't outlive the test.
    await act(async () => {
      tree.unmount();
    });
  });

  it("the four settled/load states are mutually exclusive (only one visible label at a time)", async () => {
    // Uncounted range: the loading, error, and empty labels must all be absent.
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest
          .fn()
          .mockResolvedValue([makeSummary(TODAY, 0, null, false, 4)])}
        now={NOW}
      />,
    );
    await act(async () => {});

    const labels = (label: string) =>
      tree.root.findAll((n) => n.props.accessibilityLabel === label).length;
    expect(labels("4 entries awaiting details")).toBeGreaterThan(0);
    expect(labels("Loading intake adherence")).toBe(0);
    expect(labels("No intake logged for this range")).toBe(0);
    expect(labels("Intake adherence failed to load")).toBe(0);
    expect(
      tree.root.findAll((n) => n.props.accessibilityRole === "alert").length,
    ).toBe(0);
  });
});

// Accessibility
// ─────────────────────────────────────────────────────────────────────────────

describe("TrendsScreen — accessibility", () => {
  it("chart view has an accessibilityLabel (text alternative) when entries exist", async () => {
    const entries = [
      makeEntry("1", 70, "2026-06-01"),
      makeEntry("2", 71, "2026-06-10"),
    ];
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue(entries)}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
        unitsPreference="metric"
      />,
    );
    await act(async () => {});

    const chartImage = tree.root.find(
      (n) => n.props.accessibilityRole === "image" && typeof n.props.accessibilityLabel === "string",
    );
    expect(chartImage.props.accessibilityLabel).toBeTruthy();
    expect(chartImage.props.accessibilityLabel).toContain("trend");
  });

  it("headline delta has an accessibilityLabel", async () => {
    const entries = [
      makeEntry("1", 72, "2026-06-01"),
      makeEntry("2", 70, "2026-06-15"),
    ];
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue(entries)}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
        unitsPreference="metric"
      />,
    );
    await act(async () => {});

    // Headline container has accessibilityLabel
    const headlineNodes = tree.root.findAll(
      (n) =>
        typeof n.props.accessibilityLabel === "string" &&
        (n.props.accessibilityLabel as string).includes("weight trend"),
    );
    expect(headlineNodes.length).toBeGreaterThan(0);
  });

  it("adherence strip cells never rely on color alone (each has an accessibilityLabel)", async () => {
    const getSum = jest.fn().mockResolvedValue([
      makeSummary("2026-06-27", 2000, 2000),
    ]);
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={getSum}
        now={NOW}
      />,
    );
    await act(async () => {});

    const cells = tree.root.findAll(
      (n) =>
        typeof n.props.testID === "string" &&
        (n.props.testID as string).startsWith("adherence-cell-"),
    );
    for (const cell of cells) {
      expect(cell.props.accessibilityLabel).toBeTruthy();
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Single-title regression (FTY-151): Trends must show its title exactly once.
// The old bug rendered "Trends" twice — once in the native nav header and once
// as an in-content pageTitle. ScreenHeader replaces the in-content title and
// the native header is suppressed globally.
// ─────────────────────────────────────────────────────────────────────────────

describe("TrendsScreen — single-title regression (FTY-151)", () => {
  it("renders exactly one 'Trends' heading (accessibilityRole='header')", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([])}
        now={NOW}
      />,
    );
    await act(async () => {});

    // Filter to host (native) text nodes only — react-test-renderer also returns
    // the composite Text wrapper with the same props, so plain findAll would give 2.
    const headerNodes = tree.root.findAll(
      (n) =>
        n.props.accessibilityRole === "header" &&
        (n.type as unknown) === "Text",
    );
    expect(headerNodes).toHaveLength(1);
    expect(headerNodes[0]!.props.children).toBe("Trends");
  });

  it("renders the gear action when onPressProfile is provided", async () => {
    const onPressProfile = jest.fn();
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([])}
        now={NOW}
        onPressProfile={onPressProfile}
      />,
    );
    await act(async () => {});

    const gear = tree.root.find(
      (n) => n.props.accessibilityLabel === "Open profile",
    );
    expect(gear).toBeTruthy();
    // Gear routes to profile on press.
    act(() => gear.props.onPress());
    expect(onPressProfile).toHaveBeenCalledTimes(1);
  });

  it("renders no gear when onPressProfile is not provided", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([])}
        now={NOW}
      />,
    );
    await act(async () => {});

    const gearButtons = tree.root.findAll(
      (n) => n.props.accessibilityLabel === "Open profile",
    );
    expect(gearButtons).toHaveLength(0);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Goal-aware headline delta (FTY-189): color + narration key off the user's
// goal direction, not "down = good".
// ─────────────────────────────────────────────────────────────────────────────

describe("TrendsScreen — goal-aware headline delta", () => {
  const DECREASING = [
    makeEntry("1", 72, "2026-06-01"),
    makeEntry("2", 70, "2026-06-20"),
  ];
  const INCREASING = [
    makeEntry("1", 70, "2026-06-01"),
    makeEntry("2", 72, "2026-06-20"),
  ];

  it("loss goal + a decrease renders accentText and 'toward your goal'", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue(DECREASING)}
        getDailySummaryRange={jest.fn().mockResolvedValue([])}
        now={NOW}
        unitsPreference="metric"
        goalDirection="loss"
      />,
    );
    await act(async () => {});

    const delta = findHeadlineDeltaNode(tree);
    expect(styleColor(delta)).toBe(lightPalette.accentText);
    const headline = tree.root.findAll(
      (n) =>
        typeof n.props.accessibilityLabel === "string" &&
        (n.props.accessibilityLabel as string).includes("weight trend"),
    )[0]!;
    expect(headline.props.accessibilityLabel).toContain("toward your goal");
  });

  it("loss goal + an increase renders coral and 'away from your goal'", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue(INCREASING)}
        getDailySummaryRange={jest.fn().mockResolvedValue([])}
        now={NOW}
        unitsPreference="metric"
        goalDirection="loss"
      />,
    );
    await act(async () => {});

    const delta = findHeadlineDeltaNode(tree);
    expect(styleColor(delta)).toBe(lightPalette.coral);
    const headline = tree.root.findAll(
      (n) =>
        typeof n.props.accessibilityLabel === "string" &&
        (n.props.accessibilityLabel as string).includes("weight trend"),
    )[0]!;
    expect(headline.props.accessibilityLabel).toContain("away from your goal");
  });

  it("gain goal + an increase renders accentText and 'toward your goal'", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue(INCREASING)}
        getDailySummaryRange={jest.fn().mockResolvedValue([])}
        now={NOW}
        unitsPreference="metric"
        goalDirection="gain"
      />,
    );
    await act(async () => {});

    const delta = findHeadlineDeltaNode(tree);
    expect(styleColor(delta)).toBe(lightPalette.accentText);
    const headline = tree.root.findAll(
      (n) =>
        typeof n.props.accessibilityLabel === "string" &&
        (n.props.accessibilityLabel as string).includes("weight trend"),
    )[0]!;
    expect(headline.props.accessibilityLabel).toContain("toward your goal");
  });

  it("gain goal + a decrease renders coral and 'away from your goal' (symmetric to the loss case)", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue(DECREASING)}
        getDailySummaryRange={jest.fn().mockResolvedValue([])}
        now={NOW}
        unitsPreference="metric"
        goalDirection="gain"
      />,
    );
    await act(async () => {});

    const delta = findHeadlineDeltaNode(tree);
    expect(styleColor(delta)).toBe(lightPalette.coral);
    const headline = tree.root.findAll(
      (n) =>
        typeof n.props.accessibilityLabel === "string" &&
        (n.props.accessibilityLabel as string).includes("weight trend"),
    )[0]!;
    expect(headline.props.accessibilityLabel).toContain("away from your goal");
  });

  it("maintain goal + any real drift renders coral, not accentText", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue(INCREASING)}
        getDailySummaryRange={jest.fn().mockResolvedValue([])}
        now={NOW}
        unitsPreference="metric"
        goalDirection="maintain"
      />,
    );
    await act(async () => {});

    const delta = findHeadlineDeltaNode(tree);
    expect(styleColor(delta)).toBe(lightPalette.coral);
  });

  it("live path: an existing goal hydrated from GET /goal colors the delta with no in-session set", async () => {
    // The reviewer's core case: a returning user who never touched Settings/
    // Onboarding this session. The provider hydrates the direction from the
    // authoritative GET /goal read, so the real mounted screen (reading the live
    // provider, no injected `goalDirection` prop) colors an increase for a gain
    // goal as "toward" — not the data-starved neutral it used to show.
    const reader = jest.fn(async () => "gain" as GoalDirection);
    const tree = mount(
      <SessionProvider store={sessionStore()}>
        <GoalDirectionProvider readActiveGoalDirection={reader}>
          <TrendsScreen
            session={SESSION}
            listWeightEntries={jest.fn().mockResolvedValue(INCREASING)}
            getDailySummaryRange={jest.fn().mockResolvedValue([])}
            now={NOW}
            unitsPreference="metric"
          />
        </GoalDirectionProvider>
      </SessionProvider>,
    );
    // Flush session hydration (which the provider's goal read waits on) plus the
    // screen's own fetches; each resolves on a later tick, so drain a few.
    for (let i = 0; i < 4; i++) {
      await act(async () => {});
    }

    expect(reader).toHaveBeenCalledTimes(1);
    const delta = findHeadlineDeltaNode(tree);
    expect(styleColor(delta)).toBe(lightPalette.accentText);
    const headline = tree.root.findAll(
      (n) =>
        typeof n.props.accessibilityLabel === "string" &&
        (n.props.accessibilityLabel as string).includes("weight trend"),
    )[0]!;
    expect(headline.props.accessibilityLabel).toContain("toward your goal");
  });

  it("unknown goal direction (none reported this session) is neutral, never mis-colored 'away'", async () => {
    // No `goalDirection` prop and no provider mounted: a returning gain/maintain
    // user's increase must not be guessed as a loss-goal "away"/coral. With no
    // authoritative direction reachable the delta is neutral.
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue(INCREASING)}
        getDailySummaryRange={jest.fn().mockResolvedValue([])}
        now={NOW}
        unitsPreference="metric"
      />,
    );
    await act(async () => {});

    const delta = findHeadlineDeltaNode(tree);
    expect(styleColor(delta)).toBe(lightPalette.textSecondary);
    expect(styleColor(delta)).not.toBe(lightPalette.coral);
    const headline = tree.root.findAll(
      (n) =>
        typeof n.props.accessibilityLabel === "string" &&
        (n.props.accessibilityLabel as string).includes("weight trend"),
    )[0]!;
    expect(headline.props.accessibilityLabel).not.toContain("toward your goal");
    expect(headline.props.accessibilityLabel).not.toContain("away from your goal");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Range prose (FTY-189): no raw range key ("3M"/"6M") ever leaks into the
// headline delta copy or its accessibility label. (The range *selector*'s own
// "1M"/"3M"/"6M" button labels are the control itself, not prose describing a
// range — untouched here; restyling that control is FTY-186's scope.)
// ─────────────────────────────────────────────────────────────────────────────

describe("TrendsScreen — range prose", () => {
  it("the headline delta text and its a11y label never contain a raw range key", async () => {
    const entries = [
      makeEntry("1", 72, "2026-06-01"),
      makeEntry("2", 70, "2026-06-20"),
    ];
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue(entries)}
        getDailySummaryRange={jest.fn().mockResolvedValue([])}
        now={NOW}
        unitsPreference="metric"
      />,
    );
    await act(async () => {});

    // Switch through every range so each one's copy renders at least once.
    for (const key of ["3M", "6M", "1M"] as const) {
      selectRange(tree, key);
      await act(async () => {});

      const delta = findHeadlineDeltaNode(tree);
      expect(delta.props.children as string).not.toMatch(/\b[136]M\b/);
      expect(delta.props.children as string).toContain(rangeProse(key as DateRangeKey));

      const headline = tree.root.findAll(
        (n) =>
          typeof n.props.accessibilityLabel === "string" &&
          (n.props.accessibilityLabel as string).includes("weight trend"),
      )[0]!;
      expect(headline.props.accessibilityLabel as string).not.toMatch(/\b[136]M\b/);
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Human dates (FTY-189): day-cell a11y labels and the weight-sheet date title
// are human-formatted; no user-facing ISO date string remains.
// ─────────────────────────────────────────────────────────────────────────────

describe("TrendsScreen — human dates", () => {
  it("day-cell accessibility labels are human-formatted, not raw ISO", async () => {
    const getSum = jest.fn().mockResolvedValue([
      makeSummary("2026-06-27", 2000, 2000), // today
      makeSummary("2026-06-26", 500, 2000), // yesterday
    ]);
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={getSum}
        now={NOW}
      />,
    );
    await act(async () => {});

    const today = tree.root.find(
      (n) => n.props.testID === "adherence-cell-2026-06-27",
    );
    const yesterday = tree.root.find(
      (n) => n.props.testID === "adherence-cell-2026-06-26",
    );
    expect(today.props.accessibilityLabel).toBe("Today: on target");
    expect(yesterday.props.accessibilityLabel).toBe("Yesterday: off target");

    // No cell label anywhere is a raw ISO date.
    const cellLabels = tree.root
      .findAll((n) => typeof n.props.testID === "string" && (n.props.testID as string).startsWith("adherence-cell-"))
      .map((n) => n.props.accessibilityLabel as string);
    for (const label of cellLabels) {
      expect(label).not.toMatch(/\d{4}-\d{2}-\d{2}/);
    }
  });

  it("the weight-log sheet's date title reads 'Today', not a raw ISO date", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    await act(async () => {});

    const logBtn = tree.root.find(
      (n) => n.props.accessibilityLabel === "Log weight",
    );
    act(() => logBtn.props.onPress());
    await waitForSheetSettled(tree);

    expect(textContent(tree)).toContain("Today");
    expect(textContent(tree)).not.toMatch(/\d{4}-\d{2}-\d{2}/);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Non-color adherence cue (FTY-189): on-target vs. off-target is
// distinguishable without color (a redundant shape cue), not color alone.
// ─────────────────────────────────────────────────────────────────────────────

describe("TrendsScreen — non-color adherence cue", () => {
  it("off-target cells carry a border the on-target fill does not", async () => {
    const getSum = jest.fn().mockResolvedValue([
      makeSummary("2026-06-26", 2000, 2000), // on-target
      makeSummary("2026-06-27", 500, 2000), // off-target
    ]);
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={getSum}
        now={NOW}
      />,
    );
    await act(async () => {});

    const onTargetFill = findCellFillNode(tree, "2026-06-26");
    const offTargetFill = findCellFillNode(tree, "2026-06-27");

    const onStyle = Object.assign({}, ...(onTargetFill.props.style as object[]));
    const offStyle = Object.assign({}, ...(offTargetFill.props.style as object[]));

    expect(onStyle.borderWidth ?? 0).toBe(0);
    expect(offStyle.borderWidth).toBeGreaterThan(0);
    // The fill hue still differs too (redundant, not a replacement).
    expect(onStyle.backgroundColor).not.toBe(offStyle.backgroundColor);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Bottom clearance for the floating switcher (FTY-258): Trends' scroll content
// must reserve at least the shared switcher footprint (FTY-242's
// `floatingSwitcherClearance`) so the last card scrolls clear of the pill and
// the home indicator, and it must derive that value from the shared helper
// rather than a re-hardcoded tab-bar-era height.
// ─────────────────────────────────────────────────────────────────────────────

describe("TrendsScreen — floating switcher bottom clearance (FTY-258)", () => {
  it("reserves bottom clearance at least equal to the shared switcher inset", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    await act(async () => {});

    const scroll = tree.root.find((n) => n.props.testID === "trends-screen");
    const contentStyle = StyleSheet.flatten(scroll.props.contentContainerStyle) as {
      paddingBottom?: number;
    };

    // The safe-area bottom inset seeded by `mount`'s SafeAreaProvider metrics.
    const safeAreaBottom = 34;
    const expectedClearance = floatingSwitcherClearance(safeAreaBottom);

    expect(typeof contentStyle.paddingBottom).toBe("number");
    expect(contentStyle.paddingBottom as number).toBeGreaterThanOrEqual(
      expectedClearance,
    );
  });

  it("renders no full-width tab-bar-style bottom fade", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    await act(async () => {});

    const scrim = tree.root.findAll(
      (n) => n.props.testID === "tab-bar-scrim",
    );
    expect(scrim.length).toBe(0);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Top status-bar containment (FTY-261): the FTY-259 audit's SE captures showed
// the large weight metric riding up under the status bar once Trends is
// scrolled near the bottom, because `ScreenHeader` (the only thing covering the
// top inset) scrolls away with the body. An opaque backdrop pinned to the top
// safe-area inset must sit outside the scrollable content so the status-bar
// strip stays opaque screen chrome at any scroll position, in both palettes.
// ─────────────────────────────────────────────────────────────────────────────

describe("TrendsScreen — status-bar top containment (FTY-261)", () => {
  it("renders an opaque backdrop covering the top safe-area inset, outside the scroll content", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    await act(async () => {});

    const scroll = tree.root.find((n) => n.props.testID === "trends-screen");
    const backdrop = tree.root.find(
      (n) => n.props.testID === "trends-status-bar-backdrop",
    );

    // Sized to the safe-area top inset seeded by `mount`'s SafeAreaProvider
    // metrics, so it covers exactly the status-bar strip.
    const backdropStyle = StyleSheet.flatten(backdrop.props.style) as {
      height?: number;
      position?: string;
    };
    const safeAreaTop = 47;
    expect(backdropStyle.height).toBe(safeAreaTop);
    expect(backdropStyle.position).toBe("absolute");

    // It must not be part of the scrollable content — otherwise it would
    // scroll away with the body exactly like `ScreenHeader` does, and the
    // status bar would be exposed again once scrolled.
    const nestedInScroll = scroll.findAll(
      (n) => n.props.testID === "trends-status-bar-backdrop",
    );
    expect(nestedInScroll.length).toBe(0);

    // It never blocks scroll/tap gestures for the content underneath it.
    expect(backdrop.props.pointerEvents).toBe("none");
  });

  it("colors the backdrop from the FTY-097 surface token in both light and dark, never a hardcoded hex", async () => {
    for (const scheme of ["light", "dark"] as const) {
      const palette = scheme === "light" ? lightPalette : darkPalette;
      const tree = mount(
        <ThemeProvider override={scheme}>
          <TrendsScreen
            session={SESSION}
            listWeightEntries={jest.fn().mockResolvedValue([])}
            getDailySummaryRange={jest.fn().mockResolvedValue([
              makeSummary("2026-06-27", 0, null),
            ])}
            now={NOW}
          />
        </ThemeProvider>,
      );
      await act(async () => {});

      const backdrop = tree.root.find(
        (n) => n.props.testID === "trends-status-bar-backdrop",
      );
      const backdropStyle = StyleSheet.flatten(backdrop.props.style) as {
        backgroundColor?: string;
      };
      expect(backdropStyle.backgroundColor).toBe(palette.surface);
    }
    // The swap only matters if the token differs across palettes.
    expect(lightPalette.surface).not.toBe(darkPalette.surface);
  });
});
