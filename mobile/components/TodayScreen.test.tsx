import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { TodayScreen } from "./TodayScreen";
import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import { LogEventApiError, type LogEventDTO } from "@/api/logEvents";
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

  it("shows a nonjudgmental empty state when there are no events", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    expect(textContent(tree)).toContain("Nothing logged yet");
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
    expect(textContent(tree)).toContain("Nothing logged yet");
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
  it("renders editable item controls beneath an event that has derived items", async () => {
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

    expect(hasA11yLabel(tree, "Edit Calories")).toBe(true);
    expect(textContent(tree)).toContain("Greek yogurt");
  });

  it("reconciles a confirmed edit into the timeline", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([event({ id: "a", raw_text: "Greek yogurt", status: "completed" })]);
    const editItem = jest
      .fn()
      .mockResolvedValue(foodItem({ calories: 200, calories_estimated: 150 }));
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        editItem={editItem}
        items={{ a: [foodItem()] }}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    press(tree, "Edit Calories");
    typeInto(tree, "Calories value", "200");
    await act(async () => {
      press(tree, "Save Calories");
    });

    expect(editItem).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "food",
      "item-1",
      "calories",
      200,
    );
    const content = textContent(tree);
    expect(content).toContain("Edited");
    expect(content).toContain("was 150");
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
    expect(textContent(tree)).toContain("Nothing logged yet");
  });
});
