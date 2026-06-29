import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { TodayScreen } from "./TodayScreen";
import type { DailySummaryDTO } from "@/api/dailySummary";
import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import { LogEventApiError, type LogEventDTO } from "@/api/logEvents";
import type { SavedFoodDTO } from "@/api/savedFoods";
import type { Session } from "@/state/session";

// TodayScreen imports BarcodeScannerScreen which imports expo-camera native
// modules; mock those before any tests run.

// Capture the most-recent onBarcodeScanned so scanner tests can trigger a scan.
// Must be prefixed with "mock" to be accessible inside jest.mock() factories.
let mockTriggerScan:
  | ((result: { data: string; type: string }) => void)
  | undefined;

jest.mock("expo-camera", () => {
  // Use require() inside the factory — jest.mock() factories run before imports
  // and cannot close over module-scope variables (except mock-prefixed ones).
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactNative = require("react-native");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  return {
    useCameraPermissions: jest.fn(() => [
      { status: "granted", granted: true, canAskAgain: false, expires: "never" },
      jest.fn().mockResolvedValue({ status: "granted", granted: true }),
      jest.fn().mockResolvedValue({ status: "granted", granted: true }),
    ]),
    CameraView: jest.fn().mockImplementation(
      ({ onBarcodeScanned }: { onBarcodeScanned?: (r: { data: string; type: string }) => void }) => {
        mockTriggerScan = onBarcodeScanned;
        return ReactLib.createElement(ReactNative.View, { testID: "camera-view" });
      },
    ),
  };
});

jest.mock("expo-linking", () => ({
  openSettings: jest.fn().mockResolvedValue(undefined),
}));

const SESSION: Session = {
  serverUrl: "https://api.example.test",
  token: "test-token",
  userId: "22222222-2222-2222-2222-222222222222",
};

function event(overrides: Partial<LogEventDTO>): LogEventDTO {
  return {
    id: "id",
    user_id: SESSION!.userId,
    raw_text: "two eggs and toast",
    status: "pending",
    created_at: "2026-06-26T08:00:00Z",
    updated_at: "2026-06-26T08:00:00Z",
    ...overrides,
  };
}

// Polling is driven by an injected screen-active signal; default it off so the
// non-polling tests stay deterministic and never touch a navigation container.
const INACTIVE = () => false;

// SafeAreaProvider needs frame/insets metrics in a non-native test environment.
function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(
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

function hasA11yLabel(tree: ReactTestRenderer, label: string): boolean {
  return tree.root.findAll((n) => n.props.accessibilityLabel === label).length > 0;
}

function typeInto(tree: ReactTestRenderer, label: string, value: string): void {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onChangeText === "function",
  );
  act(() => {
    node.props.onChangeText(value);
  });
}

function press(tree: ReactTestRenderer, label: string): void {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
  act(() => {
    node.props.onPress();
  });
}

describe("TodayScreen", () => {
  it("prompts sign-in when there is no session", () => {
    const tree = mount(<TodayScreen session={null} useActive={INACTIVE} />);
    expect(textContent(tree)).toContain("Sign in to see your day");
  });

  it("loads and renders the day's events with accessible status", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "Oatmeal", status: "completed" }),
        event({ id: "b", raw_text: "Cold brew", status: "pending" }),
      ]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    expect(load).toHaveBeenCalledTimes(1);
    const content = textContent(tree);
    expect(content).toContain("Oatmeal");
    expect(content).toContain("Cold brew");
    // Pending and completed are distinguished by accessible status labels.
    expect(hasA11yLabel(tree, "Logged")).toBe(true);
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
  });

  it("shows a calm empty state invite when there are no events", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    expect(textContent(tree)).toContain("Log your first thing");
  });

  it("surfaces a load error with a retry affordance", async () => {
    const load = jest
      .fn()
      .mockRejectedValueOnce(new LogEventApiError(401, "Your session has expired."))
      .mockResolvedValueOnce([event({ id: "a", raw_text: "Oatmeal", status: "pending" })]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    expect(textContent(tree)).toContain("Your session has expired.");
    expect(hasA11yLabel(tree, "Try again")).toBe(true);

    // Retrying re-fetches and renders the recovered day.
    press(tree, "Try again");
    await act(async () => {});
    expect(textContent(tree)).toContain("Oatmeal");
  });

  it("shows a submitted entry immediately as pending, then reconciles", async () => {
    const load = jest.fn().mockResolvedValue([]);
    let resolveCreate!: (dto: LogEventDTO) => void;
    const create = jest.fn().mockReturnValue(
      new Promise<LogEventDTO>((resolve) => {
        resolveCreate = resolve;
      }),
    );
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "  greek yogurt  ");
    press(tree, "Add entry");

    // Optimistic: the entry appears as pending before the create resolves.
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "greek yogurt",
    );
    expect(textContent(tree)).toContain("greek yogurt");
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);

    await act(async () => {
      resolveCreate(
        event({ id: "server-1", raw_text: "greek yogurt", status: "pending" }),
      );
    });
    expect(textContent(tree)).toContain("greek yogurt");
  });

  it("rolls back and restores input when create fails", async () => {
    // Fake timers prevent the restored text from leaking a dangling debounce
    // timer that would fire after Jest tears down the test.
    jest.useFakeTimers();
    try {
      const load = jest.fn().mockResolvedValue([]);
      const create = jest
        .fn()
        .mockRejectedValue(new LogEventApiError(422, "That entry couldn't be saved."));
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          create={create}
          useActive={INACTIVE}
        />,
      );
      await act(async () => {});

      typeInto(tree, "Log food or exercise", "blernsday");
      await act(async () => {
        press(tree, "Add entry");
      });

      expect(textContent(tree)).toContain("That entry couldn't be saved.");
      // Optimistic entry rolled back to the empty state.
      expect(textContent(tree)).toContain("Log your first thing");
    } finally {
      jest.useRealTimers();
    }
  });
});

function foodItem(
  overrides: Partial<DerivedFoodItemDTO> = {},
): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: "item-1",
    user_id: SESSION!.userId,
    log_event_id: "a",
    name: "Greek yogurt",
    quantity_text: "1 cup",
    unit: "cup",
    amount: 1,
    status: "resolved",
    grams: 245,
    calories: 150,
    protein_g: 20,
    carbs_g: 8,
    fat_g: 4,
    calories_estimated: 150,
    protein_g_estimated: 20,
    carbs_g_estimated: 8,
    fat_g_estimated: 4,
    created_at: "2026-06-26T08:00:00Z",
    updated_at: "2026-06-26T08:00:00Z",
    ...overrides,
  };
}

describe("TodayScreen derived items", () => {
  it("renders item rows (name · kcal) for a completed event with derived items", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([event({ id: "a", raw_text: "Greek yogurt", status: "completed" })]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        items={{ a: [foodItem()] }}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // The new design shows item rows (name · kcal · source icon) for completed events
    expect(textContent(tree)).toContain("Greek yogurt");
    expect(textContent(tree)).toContain("150 kcal");
  });

  it("shows a pending placeholder row for an event without derived items yet", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([event({ id: "b", raw_text: "Cold brew", status: "pending" })]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        items={{}}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // Pending events without items show a status placeholder (raw_text + status icon)
    expect(textContent(tree)).toContain("Cold brew");
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
  });
});

describe("TodayScreen polling", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("auto-refreshes a pending entry to its terminal status", async () => {
    const load = jest
      .fn()
      .mockResolvedValueOnce([event({ id: "a", raw_text: "Oatmeal", status: "pending" })])
      .mockResolvedValueOnce([event({ id: "a", raw_text: "Oatmeal", status: "completed" })]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        useActive={() => true}
        pollIntervalMs={1000}
      />,
    );
    await act(async () => {});
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);

    // One interval later the screen polls and reconciles to the terminal status.
    act(() => jest.advanceTimersByTime(1000));
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(2);
    expect(hasA11yLabel(tree, "Logged")).toBe(true);

    // Nothing is pending now, so polling stops — no further loads.
    act(() => jest.advanceTimersByTime(5000));
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("does not poll while the screen is inactive (backgrounded/unfocused)", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([event({ id: "a", status: "pending" })]);
    mount(
      <TodayScreen
        session={SESSION}
        load={load}
        useActive={() => false}
        pollIntervalMs={1000}
      />,
    );
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(1);

    act(() => jest.advanceTimersByTime(5000));
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("keeps the timeline intact when a poll fails, then recovers", async () => {
    const load = jest
      .fn()
      .mockResolvedValueOnce([event({ id: "a", raw_text: "Oatmeal", status: "pending" })])
      .mockRejectedValueOnce(new LogEventApiError(500, "transient"))
      .mockResolvedValueOnce([event({ id: "a", raw_text: "Oatmeal", status: "completed" })]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        useActive={() => true}
        pollIntervalMs={1000}
      />,
    );
    await act(async () => {});
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);

    // A failed poll is swallowed; the pending entry is still shown.
    act(() => jest.advanceTimersByTime(1000));
    await act(async () => {});
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);

    // The next tick recovers and reconciles to the terminal status.
    act(() => jest.advanceTimersByTime(1000));
    await act(async () => {});
    expect(hasA11yLabel(tree, "Logged")).toBe(true);
  });
});

// ─── Barcode scan entry point ─────────────────────────────────────────────────

describe("TodayScreen barcode scanning", () => {
  beforeEach(() => {
    mockTriggerScan = undefined;
  });

  it("exposes an accessible Scan barcode entry point", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});
    expect(hasA11yLabel(tree, "Scan barcode")).toBe(true);
  });

  it("shows the scanner modal when the scan entry point is pressed", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    press(tree, "Scan barcode");
    // After pressing, the CameraView mock renders and captures onBarcodeScanned.
    expect(hasA11yLabel(tree, "Close scanner")).toBe(true);
  });

  it("a successful barcode read submits via createLogEvent and appears as pending", async () => {
    const load = jest.fn().mockResolvedValue([]);
    let resolveCreate!: (dto: LogEventDTO) => void;
    const create = jest.fn().mockReturnValue(
      new Promise<LogEventDTO>((resolve) => {
        resolveCreate = resolve;
      }),
    );
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    press(tree, "Scan barcode");

    act(() => {
      mockTriggerScan?.({ data: "5901234123457", type: "ean13" });
    });

    // create is called with the barcode string (not an image URI or object)
    expect(create).toHaveBeenCalledTimes(1);
    const [, rawText] = create.mock.calls[0];
    expect(rawText).toBe("5901234123457");

    // Entry appears immediately as pending before create resolves
    expect(textContent(tree)).toContain("5901234123457");
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);

    // Reconcile with server response
    await act(async () => {
      resolveCreate(
        event({ id: "server-1", raw_text: "5901234123457", status: "pending" }),
      );
    });
    expect(textContent(tree)).toContain("5901234123457");
  });

  it("rolls back and surfaces an error when the barcode submit fails", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const create = jest
      .fn()
      .mockRejectedValue(
        new LogEventApiError(422, "That entry couldn't be saved."),
      );
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    press(tree, "Scan barcode");

    await act(async () => {
      mockTriggerScan?.({ data: "5901234123457", type: "ean13" });
    });

    // Optimistic entry rolled back; error surfaced.
    expect(textContent(tree)).toContain("That entry couldn't be saved.");
    expect(textContent(tree)).toContain("Log your first thing");
  });
});

// ─── Label capture entry point (FTY-064) ─────────────────────────────────────

describe("TodayScreen label capture", () => {
  it("exposes an accessible Capture label entry point", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});
    expect(hasA11yLabel(tree, "Capture label")).toBe(true);
  });

  it("shows the label capture modal when the label entry point is pressed", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    press(tree, "Capture label");

    // After pressing, the CameraCapture scaffold renders (permission granted by the mock).
    expect(hasA11yLabel(tree, "Close scanner")).toBe(true);
  });

  it("adds the uploaded label event to the timeline via FTY-032 polling", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const createdEvent: LogEventDTO = {
      id: "label-server-1",
      user_id: SESSION!.userId,
      raw_text: "nutrition label photo",
      status: "pending",
      created_at: "2026-06-27T10:00:00Z",
      updated_at: "2026-06-27T10:00:00Z",
    };
    // The upload function returns the created pending event.
    const uploadLabel = jest.fn().mockResolvedValue(createdEvent);
    // The takePhoto mock skips the real camera ref.
    const labelTakePhoto = jest.fn().mockResolvedValue({ uri: "file:///label.jpg" });

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        useActive={INACTIVE}
        uploadLabel={uploadLabel}
        labelTakePhoto={labelTakePhoto}
      />,
    );
    await act(async () => {});

    // Open label capture modal.
    press(tree, "Capture label");

    // Take photo.
    await act(async () => {
      press(tree, "Take photo");
    });

    // Upload.
    await act(async () => {
      press(tree, "Upload label");
    });

    // The uploaded event appears on the timeline as pending.
    expect(textContent(tree)).toContain("nutrition label photo");
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
  });
});

// ─── Typeahead suggestion bar + saved food apply (FTY-053) ───────────────────

function savedFood(overrides: Partial<SavedFoodDTO> = {}): SavedFoodDTO {
  return {
    id: "sf-1",
    user_id: SESSION!.userId,
    name: "Greek yogurt",
    calories: 200,
    protein_g: 22,
    carbs_g: 10,
    fat_g: 5,
    serving_size: 1,
    serving_unit: "cup",
    source: "saved_from_correction",
    created_at: "2026-06-27T10:00:00Z",
    updated_at: "2026-06-27T10:00:00Z",
    ...overrides,
  };
}

// ─── Daily summary header (FTY-075) ──────────────────────────────────────────

function summary(overrides: Partial<DailySummaryDTO> = {}): DailySummaryDTO {
  return {
    date: "2026-06-27",
    intake: { calories: 1234, protein_g: 70, carbs_g: 120, fat_g: 40 },
    has_intake: true,
    target: {
      calories: { effective: 2000, derived: 2000, source: "derived" },
      protein_g: { effective: 128, derived: 128, source: "derived" },
      carbs_g: { effective: 148, derived: 148, source: "derived" },
      fat_g: { effective: 64, derived: 64, source: "derived" },
    },
    exercise: { active_calories: 0 },
    ...overrides,
  };
}

describe("TodayScreen daily summary", () => {
  it("fetches and renders the day's summary figures", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([event({ id: "a", raw_text: "Oatmeal", status: "completed" })]);
    const getDailySummary = jest.fn().mockResolvedValue(summary());
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getDailySummary={getDailySummary}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    expect(getDailySummary).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
    );
    // Hero combined label includes consumed and target.
    const labels = tree.root
      .findAll((n) => !!n.props.accessibilityLabel)
      .map((n) => n.props.accessibilityLabel as string);
    expect(labels.some((l) => l.includes("1,234 of 2,000 kcal"))).toBe(true);
  });

  it("surfaces a summary error string when the fetch fails", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([event({ id: "a", raw_text: "Oatmeal", status: "completed" })]);
    const getDailySummary = jest.fn().mockRejectedValue(new Error("network"));
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getDailySummary={getDailySummary}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    expect(textContent(tree)).toContain("We couldn't load your summary");
  });

  it("shows the zeroed summary and target on an empty day", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const getDailySummary = jest
      .fn()
      .mockResolvedValue(
        summary({ intake: { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 } }),
      );
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getDailySummary={getDailySummary}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // The empty-state invite and the hero coexist: full budget is visible
    // before the first entry is logged.
    expect(textContent(tree)).toContain("Log your first thing");
    const labels = tree.root
      .findAll((n) => !!n.props.accessibilityLabel)
      .map((n) => n.props.accessibilityLabel as string);
    expect(labels.some((l) => l.includes("0 of 2,000 kcal"))).toBe(true);
    expect(labels.some((l) => l.includes("2,000 remaining"))).toBe(true);
  });

  describe("with polling", () => {
    beforeEach(() => jest.useFakeTimers());
    afterEach(() => jest.useRealTimers());

    it("refreshes the summary and clears a stale error once a poll recovers", async () => {
      // A pending entry keeps polling active. The summary fetch fails on initial
      // load, then recovers on the next poll — the error banner must clear.
      const load = jest
        .fn()
        .mockResolvedValue([event({ id: "a", raw_text: "Oatmeal", status: "pending" })]);
      const getDailySummary = jest
        .fn()
        .mockRejectedValueOnce(new Error("network"))
        .mockResolvedValue(summary({ intake: { calories: 1500, protein_g: 80, carbs_g: 150, fat_g: 50 } }));
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          getDailySummary={getDailySummary}
          useActive={() => true}
          pollIntervalMs={1000}
        />,
      );
      await act(async () => {});

      // Initial load failed: the error banner is shown, no figures yet.
      expect(textContent(tree)).toContain("We couldn't load your summary");

      // One interval later the poll refetches and succeeds.
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});

      expect(textContent(tree)).not.toContain("We couldn't load your summary");
      // Hero label now includes the recovered intake figure
      const labels = tree.root
        .findAll((n) => !!n.props.accessibilityLabel)
        .map((n) => n.props.accessibilityLabel as string);
      expect(labels.some((l) => l.includes("1,500"))).toBe(true); // recovered figure
    });
  });
});

describe("TodayScreen typeahead suggestion bar", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("queries saved foods as the user types (after debounce)", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const searchSavedFoods = jest
      .fn()
      .mockResolvedValue({ items: [savedFood()], limit: 20 });

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        searchSavedFoods={searchSavedFoods}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "greek");

    // No search before the debounce window.
    expect(searchSavedFoods).not.toHaveBeenCalled();

    await act(async () => {
      jest.advanceTimersByTime(400);
    });

    expect(searchSavedFoods).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "greek",
    );
  });

  it("shows suggestion chips for matching saved foods", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const searchSavedFoods = jest
      .fn()
      .mockResolvedValue({ items: [savedFood({ name: "Greek yogurt" })], limit: 20 });

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        searchSavedFoods={searchSavedFoods}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "greek");
    await act(async () => {
      jest.advanceTimersByTime(400);
    });

    expect(textContent(tree)).toContain("Greek yogurt");
    expect(hasA11yLabel(tree, "Use saved food: Greek yogurt")).toBe(true);
  });

  it("applies the saved food's values as a synthetic item and marks source=saved_food on submit", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const yogurt = savedFood();
    const searchSavedFoods = jest
      .fn()
      .mockResolvedValue({ items: [yogurt], limit: 20 });
    let resolveCreate!: (dto: LogEventDTO) => void;
    const create = jest.fn().mockReturnValue(
      new Promise<LogEventDTO>((resolve) => {
        resolveCreate = resolve;
      }),
    );

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        searchSavedFoods={searchSavedFoods}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "greek");
    await act(async () => {
      jest.advanceTimersByTime(400);
    });

    // Tap the suggestion.
    press(tree, "Use saved food: Greek yogurt");

    // Press Add; the item should appear immediately with saved food values.
    press(tree, "Add entry");

    // The saved food's nutrition is shown immediately (estimator skipped).
    const content = textContent(tree);
    expect(content).toContain("Greek yogurt");
    expect(content).toContain("200");  // calories from saved food

    // Confirm the log event was still created (for persistence).
    expect(create).toHaveBeenCalledTimes(1);

    // Resolve the create; the item should re-key to the real event id.
    await act(async () => {
      resolveCreate(event({ id: "server-2", raw_text: "Greek yogurt", status: "pending" }));
    });

    // Item is still shown with saved food values after reconciliation.
    expect(textContent(tree)).toContain("Greek yogurt");
    expect(textContent(tree)).toContain("200");
  });

  it("leaves the normal estimator path intact when no suggestion is selected", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const searchSavedFoods = jest
      .fn()
      .mockResolvedValue({ items: [], limit: 20 });
    const create = jest.fn().mockResolvedValue(
      event({ id: "server-3", raw_text: "banana", status: "pending" }),
    );

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        searchSavedFoods={searchSavedFoods}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "banana");
    await act(async () => {
      press(tree, "Add entry");
    });

    // Normal entry created; no synthetic item.
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "banana",
    );
    expect(textContent(tree)).toContain("banana");
  });

  it("rolls back the synthetic item when create fails after a suggestion is tapped", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const yogurt = savedFood();
    const searchSavedFoods = jest
      .fn()
      .mockResolvedValue({ items: [yogurt], limit: 20 });
    const create = jest
      .fn()
      .mockRejectedValue(new LogEventApiError(422, "That entry couldn't be saved."));

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        searchSavedFoods={searchSavedFoods}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "greek");
    await act(async () => {
      jest.advanceTimersByTime(400);
    });
    press(tree, "Use saved food: Greek yogurt");
    await act(async () => {
      press(tree, "Add entry");
    });

    // Entry and synthetic item rolled back; error surfaced.
    expect(textContent(tree)).toContain("That entry couldn't be saved.");
    expect(textContent(tree)).toContain("Log your first thing");
  });
});
