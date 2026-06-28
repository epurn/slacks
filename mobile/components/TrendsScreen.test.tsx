import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { TrendsScreen } from "./TrendsScreen";
import {
  WeightApiError,
  type WeightEntryDTO,
} from "@/api/weightEntries";
import type { DailySummaryDTO, TargetReadModel } from "@/api/dailySummary";
import type { Session } from "@/state/session";
import type { CadenceStore, NotificationsAdapter, WeighInCadence } from "@/state/reminderScheduler";

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

const SESSION: Session = {
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
): DailySummaryDTO {
  return {
    date,
    intake: { calories: intake, protein_g: 80, carbs_g: 150, fat_g: 40 },
    has_intake: hasIntake,
    target: targetCal !== null ? makeTarget(targetCal) : null,
    exercise: { active_calories: 0 },
  };
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

function textContent(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

// ─────────────────────────────────────────────────────────────────────────────
// No session
// ─────────────────────────────────────────────────────────────────────────────

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

// ─────────────────────────────────────────────────────────────────────────────
// Weight entries loading
// ─────────────────────────────────────────────────────────────────────────────

describe("TrendsScreen — weight entries", () => {
  it("shows loading state while entries are fetching", () => {
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

// ─────────────────────────────────────────────────────────────────────────────
// Range selector
// ─────────────────────────────────────────────────────────────────────────────

describe("TrendsScreen — range selector", () => {
  it("renders range buttons for 1M, 3M, 6M", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    await act(async () => {});
    const btn1m = tree.root.find(
      (n) => n.props.testID === "range-btn-1M",
    );
    const btn3m = tree.root.find(
      (n) => n.props.testID === "range-btn-3M",
    );
    const btn6m = tree.root.find(
      (n) => n.props.testID === "range-btn-6M",
    );
    expect(btn1m).toBeTruthy();
    expect(btn3m).toBeTruthy();
    expect(btn6m).toBeTruthy();
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
    const btn3m = tree.root.find((n) => n.props.testID === "range-btn-3M");
    act(() => btn3m.props.onPress());
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

    const btn3m = tree.root.find((n) => n.props.testID === "range-btn-3M");
    act(() => btn3m.props.onPress());
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

// ─────────────────────────────────────────────────────────────────────────────
// Headline delta
// ─────────────────────────────────────────────────────────────────────────────

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
});

// ─────────────────────────────────────────────────────────────────────────────
// Adherence summary
// ─────────────────────────────────────────────────────────────────────────────

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

// ─────────────────────────────────────────────────────────────────────────────
// Past-day drilldown
// ─────────────────────────────────────────────────────────────────────────────

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

// ─────────────────────────────────────────────────────────────────────────────
// Weight entry sheet
// ─────────────────────────────────────────────────────────────────────────────

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

    // Modal appears (visible prop becomes true on the WeightLogSheet)
    const modal = tree.root.find(
      (n) => n.props.visible !== undefined && n.props.animationType === "slide",
    );
    expect(modal).toBeTruthy();
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
// Cadence picker
// ─────────────────────────────────────────────────────────────────────────────

describe("TrendsScreen — cadence picker", () => {
  it("renders all cadence options", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    await act(async () => {});

    ["weekly", "biweekly", "monthly", "off"].forEach((val) => {
      const opt = tree.root.find(
        (n) => n.props.testID === `cadence-option-${val}`,
      );
      expect(opt).toBeTruthy();
    });
  });

  it("changing cadence to Off cancels the reminder", async () => {
    const store = mockStore("weekly");
    const notifications = mockNotifications();

    // Start with a logged entry so we have a last weigh-in date
    const list = jest.fn().mockResolvedValue([makeEntry("1", 70, "2026-06-20")]);

    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={list}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        store={store}
        notifications={notifications}
        now={NOW}
      />,
    );
    await act(async () => {});

    const offOpt = tree.root.find(
      (n) => n.props.testID === "cadence-option-off",
    );
    act(() => offOpt.props.onPress());
    await act(async () => {});

    // After setting Off, no scheduled notifications
    expect(notifications.scheduled).toHaveLength(0);
  });

  it("due-only: changing cadence to Weekly schedules exactly one notification", async () => {
    const store = mockStore("off");
    const notifications = mockNotifications();

    const list = jest.fn().mockResolvedValue([makeEntry("1", 70, "2026-06-20")]);

    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={list}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        store={store}
        notifications={notifications}
        now={NOW}
      />,
    );
    await act(async () => {});

    const weeklyOpt = tree.root.find(
      (n) => n.props.testID === "cadence-option-weekly",
    );
    act(() => weeklyOpt.props.onPress());
    await act(async () => {});

    // Exactly one notification scheduled
    expect(notifications.scheduled).toHaveLength(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
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

  it("cadence options have accessibilityRole='radio'", async () => {
    const tree = mount(
      <TrendsScreen
        session={SESSION}
        listWeightEntries={jest.fn().mockResolvedValue([])}
        getDailySummaryRange={jest.fn().mockResolvedValue([makeSummary("2026-06-27", 0, null)])}
        now={NOW}
      />,
    );
    await act(async () => {});

    const radioOpts = tree.root.findAll(
      (n) => n.props.accessibilityRole === "radio",
    );
    expect(radioOpts.length).toBeGreaterThanOrEqual(4);
  });
});
