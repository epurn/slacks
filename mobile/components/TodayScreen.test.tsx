import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { TodayScreen } from "./TodayScreen";
import type { DailySummaryDTO } from "@/api/dailySummary";
import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import { LogEventApiError, type LogEventDTO } from "@/api/logEvents";
import type { SavedFoodDTO } from "@/api/savedFoods";
import type { OutboxEntry, OutboxStore } from "@/state/outbox";
import type { Session } from "@/state/session";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

// TodayScreen imports BarcodeScannerScreen which imports expo-camera native
// modules; mock those before any tests run.

// Capture the most-recent onBarcodeScanned so scanner tests can trigger a scan.
// Must be prefixed with "mock" to be accessible inside jest.mock() factories.
let mockTriggerScan:
  | ((result: { data: string; type: string }) => void)
  | undefined;

// TodayScreen now renders AppIcon (expo-symbols) for the gear button; stub the
// native SymbolView so tests run without a native module.
jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactNative = require("react-native");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  return {
    SymbolView: ({ name, accessibilityLabel }: { name: string; accessibilityLabel?: string }) =>
      ReactLib.createElement(ReactNative.View, {
        testID: `sf-symbol-${String(name)}`,
        accessibilityLabel,
      }),
  };
});

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

// Unmount every tree after each test so a background interval (e.g. the offline
// outbox retry timer) can never fire into a later test and update an unmounted
// component.
const activeTrees: ReactTestRenderer[] = [];

beforeEach(() => mockReduceMotion(false));

afterEach(() => {
  for (const tree of activeTrees) {
    try {
      act(() => tree.unmount());
    } catch {
      // Already unmounted / torn down — ignore.
    }
  }
  activeTrees.length = 0;
});

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
  activeTrees.push(tree);
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

function inputValue(tree: ReactTestRenderer, label: string): string {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onChangeText === "function",
  );
  return node.props.value as string;
}

/** A network-layer failure (server unreachable), distinct from an API error. */
function networkError(): Error {
  return new TypeError("Network request failed");
}

/** An in-memory OutboxStore for tests, with the backing data exposed. */
function memoryStore(initial: Record<string, OutboxEntry[]> = {}): {
  store: OutboxStore;
  data: Map<string, OutboxEntry[]>;
} {
  const data = new Map<string, OutboxEntry[]>(
    Object.entries(initial).map(([k, v]) => [k, [...v]]),
  );
  const store: OutboxStore = {
    load: async (userId) => data.get(userId) ?? [],
    save: async (userId, entries) => {
      data.set(userId, [...entries]);
    },
    clear: async (userId) => {
      data.delete(userId);
    },
  };
  return { store, data };
}

/** A deterministic, monotonically-increasing idempotency-key generator. */
function sequentialKeys(): () => string {
  let n = 0;
  return () => `key-${n++}`;
}

/**
 * A clarification read that returns no persisted question — the clarify sheet
 * falls back to the generic prompt + free-text. Injected so clarify-mode tests
 * that don't exercise the question stay deterministic (no real fetch).
 */
function emptyClarification(): jest.Mock {
  return jest.fn().mockResolvedValue({ questions: [] });
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
        getClarification={emptyClarification()}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "  greek yogurt  ");
    press(tree, "Add entry");

    // Optimistic: the entry appears as pending before the create resolves.
    // create carries the FTY-096 idempotency key minted by the submit machine.
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "greek yogurt",
      expect.any(String),
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

// ─── Correction / detail sheet wiring (FTY-148) ──────────────────────────────

/** Resolve the style object for a node, collapsing a Pressable style function. */
function resolvedStyle(node: { props: { style?: unknown } }): Record<string, unknown> {
  const raw =
    typeof node.props.style === "function"
      ? (node.props.style as (s: { pressed: boolean }) => unknown)({ pressed: false })
      : node.props.style;
  return Object.assign(
    {},
    ...([] as unknown[]).concat(raw).filter(Boolean) as Record<string, unknown>[],
  );
}

describe("TodayScreen correction sheet wiring", () => {
  it("opens the correction sheet for a tapped completed item; the sheet is not mounted until then", async () => {
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

    // Dead until wired: the sheet (and its stepper) is not in the tree yet.
    expect(hasA11yLabel(tree, "Increase amount")).toBe(false);

    // Tapping the completed item row opens the sheet (mounted, reachable).
    press(tree, "Greek yogurt, 150 kcal");
    expect(hasA11yLabel(tree, "Increase amount")).toBe(true);
    expect(hasA11yLabel(tree, "Decrease amount")).toBe(true);
  });

  it("opens the sheet for the specific item that was tapped", async () => {
    const editItem = jest.fn().mockResolvedValue(foodItem({ id: "item-b" }));
    const load = jest
      .fn()
      .mockResolvedValue([event({ id: "a", raw_text: "Two snacks", status: "completed" })]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        editItem={editItem}
        items={{
          a: [
            foodItem({ id: "item-a", name: "Apple", calories: 95 }),
            foodItem({ id: "item-b", name: "Banana", calories: 105 }),
          ],
        }}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // Tap the second row, then exercise a lever; the edit targets that item's id.
    press(tree, "Banana, 105 kcal");
    await act(async () => {
      press(tree, "Increase amount");
    });

    expect(editItem).toHaveBeenCalledTimes(1);
    const [, itemType, itemId] = editItem.mock.calls[0];
    expect(itemType).toBe("food");
    expect(itemId).toBe("item-b");
  });

  it("drives the portion stepper end-to-end and reflects the recomputed item on close", async () => {
    // The server recomputes calories for the new portion; the UI re-renders the
    // returned values (never client math) and the timeline reflects them on close.
    const editItem = jest
      .fn()
      .mockResolvedValue(foodItem({ amount: 1.25, calories: 188 }));
    const load = jest
      .fn()
      .mockResolvedValue([event({ id: "a", raw_text: "Greek yogurt", status: "completed" })]);
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

    press(tree, "Greek yogurt, 150 kcal");
    await act(async () => {
      press(tree, "Increase amount");
    });

    // FTY-092 amount-adjust called with the stepped quantity; server values shown.
    expect(editItem).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "food",
      "item-1",
      "quantity",
      1.25,
    );
    expect(textContent(tree)).toContain("188");

    // Closing returns to the timeline, which now reflects the recomputed value.
    press(tree, "Close");
    expect(hasA11yLabel(tree, "Increase amount")).toBe(false);
    expect(hasA11yLabel(tree, "Greek yogurt, 188 kcal")).toBe(true);
  });

  it("exposes a ≥44pt tap target with a VoiceOver label on the completed item row", async () => {
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

    const row = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Greek yogurt, 150 kcal" &&
        typeof n.props.onPress === "function",
    );
    expect(row.props.accessibilityRole).toBe("button");
    expect(row.props.accessibilityHint).toBe("Tap to view details");
    expect(resolvedStyle(row).minHeight).toBeGreaterThanOrEqual(44);
  });
});

// ─── Needs-clarification legibility + clarify-mode wiring (FTY-149) ───────────

describe("TodayScreen needs-clarification entries", () => {
  it("renders a needs_clarification entry legibly and invitingly, never a silent row", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    const text = textContent(tree);
    expect(text).toContain("Add a detail");
    expect(text).toContain("milk");
  });

  it("exposes the needs-a-detail state and a resolve hint to VoiceOver on a ≥44pt target", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    const row = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "milk, needs a detail, uncounted" &&
        typeof n.props.onPress === "function",
    );
    expect(row.props.accessibilityRole).toBe("button");
    expect(row.props.accessibilityHint).toBe(
      "Tap to see the full phrase and add the missing detail",
    );
    expect(resolvedStyle(row).minHeight).toBeGreaterThanOrEqual(44);
  });

  it("opens the correction sheet in clarify-mode on tap, with no auto-filled detail", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getClarification={emptyClarification()}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // The clarify free-text input is not mounted until the row is tapped.
    expect(hasA11yLabel(tree, "Your answer")).toBe(false);

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });

    // Clarify-mode is shown: free-text fallback present, and the missing detail
    // is never pre-filled (Fatty does not fabricate the answer).
    expect(hasA11yLabel(tree, "Your answer")).toBe(true);
    expect(inputValue(tree, "Your answer")).toBe("");
    // Clarify-mode only — the amount stepper / change-match levers stay hidden.
    expect(hasA11yLabel(tree, "Increase amount")).toBe(false);
  });

  it("resolves via the answer round-trip so the SAME entry recomputes in place — no create, no duplicate", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const create = jest.fn();
    // The round-trip returns the SAME event (id "a"), transitioned to processing,
    // with its raw phrase untouched — the backend re-estimates it in place.
    const answerClarification = jest
      .fn()
      .mockResolvedValue(
        event({ id: "a", raw_text: "milk", status: "processing" }),
      );
    const getClarification = jest.fn().mockResolvedValue({
      questions: [
        { id: "q1", text: "What kind of milk?", options: ["Whole", "2%", "Skim"] },
      ],
    });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        answerClarification={answerClarification}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });
    // Tap the "2%" quick-pick chip → one tap resolves via the answer round-trip.
    await act(async () => {
      press(tree, "2%");
    });

    // The answer travels the first-class round-trip keyed on the event + question
    // id — never the create path — so no second event is spawned and the raw
    // phrase is never mutated (audit A3/A5).
    expect(answerClarification).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "a",
      "q1",
      "2%",
    );
    expect(create).not.toHaveBeenCalled();

    // The same entry transitions in place (→ processing): its needs-a-detail
    // treatment is gone, and no duplicate "milk" row stands in for it.
    expect(hasA11yLabel(tree, "milk, needs a detail, uncounted")).toBe(false);
  });

  it("resolves a free-text answer via the round-trip when options are absent", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const answerClarification = jest
      .fn()
      .mockResolvedValue(
        event({ id: "a", raw_text: "milk", status: "processing" }),
      );
    // A deterministic backend-raised question carries no options — free text only.
    const getClarification = jest.fn().mockResolvedValue({
      questions: [{ id: "q1", text: "What kind of milk?", options: [] }],
    });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        answerClarification={answerClarification}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });
    typeInto(tree, "Your answer", "Oat milk");
    await act(async () => {
      press(tree, "Submit answer");
    });

    expect(answerClarification).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "a",
      "q1",
      "Oat milk",
    );
    expect(hasA11yLabel(tree, "milk, needs a detail, uncounted")).toBe(false);
  });

  it("surfaces an error and keeps the entry actionable when the answer round-trip fails", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const answerClarification = jest
      .fn()
      .mockRejectedValue(
        new LogEventApiError(422, "That entry couldn't be saved."),
      );
    const getClarification = jest.fn().mockResolvedValue({
      questions: [
        { id: "q1", text: "What kind of milk?", options: ["Whole", "2%", "Skim"] },
      ],
    });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        answerClarification={answerClarification}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });
    await act(async () => {
      press(tree, "2%");
    });

    // The answer failed: the entry stays as needs_clarification (still tappable,
    // never a dead end), and the failure is surfaced rather than swallowed.
    expect(answerClarification).toHaveBeenCalled();
    expect(hasA11yLabel(tree, "milk, needs a detail, uncounted")).toBe(true);
    expect(textContent(tree)).toContain("That entry couldn't be saved.");
  });

  it("keeps the resolved entry advanced after a poll re-fetches the processing event", async () => {
    jest.useFakeTimers();
    try {
      const needsClar = event({
        id: "a",
        raw_text: "milk",
        status: "needs_clarification",
      });
      const processing = event({
        id: "a",
        raw_text: "milk",
        status: "processing",
      });
      // Initial load returns the needs_clarification row; after the answer
      // advances it server-side, every subsequent poll returns the processing
      // event for the SAME id.
      const load = jest
        .fn()
        .mockResolvedValueOnce([needsClar])
        .mockResolvedValue([processing]);
      const answerClarification = jest.fn().mockResolvedValue(processing);
      const getClarification = jest.fn().mockResolvedValue({
        questions: [
          { id: "q1", text: "What kind of milk?", options: ["Whole", "2%", "Skim"] },
        ],
      });
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          answerClarification={answerClarification}
          getClarification={getClarification}
          useActive={() => true}
          pollIntervalMs={1000}
        />,
      );
      await act(async () => {});

      await act(async () => {
        press(tree, "milk, needs a detail, uncounted");
      });
      await act(async () => {
        press(tree, "2%");
      });

      // The event is processing → polling runs and re-fetches the same event
      // (now processing). It must stay advanced in place, never revert to the
      // needs-a-detail treatment and never appear twice.
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});

      expect(hasA11yLabel(tree, "milk, needs a detail, uncounted")).toBe(false);
    } finally {
      jest.useRealTimers();
    }
  });

  it("fetches the clarification read and shows Fatty's real question + quick-pick chips", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "peanut butter", status: "needs_clarification" }),
      ]);
    const getClarification = jest.fn().mockResolvedValue({
      questions: [
        {
          id: "q1",
          text: "How much peanut butter?",
          options: ["1 tbsp", "2 tbsp"],
        },
        { id: "q2", text: "Smooth or crunchy?", options: [] },
      ],
    });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "peanut butter, needs a detail, uncounted");
    });

    // The read is scoped to the tapped event, and the primary question is shown
    // verbatim — not the generic "We need a detail…" fallback.
    expect(getClarification).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "a",
    );
    expect(textContent(tree)).toContain("How much peanut butter?");
    expect(textContent(tree)).not.toContain("We need a detail");
    // The payload's candidate options render as tappable quick-pick chips.
    expect(hasA11yLabel(tree, "1 tbsp")).toBe(true);
    expect(hasA11yLabel(tree, "2 tbsp")).toBe(true);
    // The free-text fallback stays reachable alongside the chips.
    expect(hasA11yLabel(tree, "Your answer")).toBe(true);
    expect(hasA11yLabel(tree, "Submit answer")).toBe(true);
  });

  it("falls back to the generic prompt + free-text when the read returns no question", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const getClarification = jest.fn().mockResolvedValue({ questions: [] });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });

    // No persisted question → the generic prompt + free-text fallback remain
    // usable; the user is never blocked.
    expect(textContent(tree)).toContain("We need a detail");
    expect(hasA11yLabel(tree, "Your answer")).toBe(true);
    expect(hasA11yLabel(tree, "Submit answer")).toBe(true);
  });

  it("keeps the free-text fallback usable when the clarification read fails", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const getClarification = jest
      .fn()
      .mockRejectedValue(new LogEventApiError(404, "We couldn't find your log."));
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });

    // A failed read never blocks the flow: the fallback prompt + free-text stand.
    expect(textContent(tree)).toContain("We need a detail");
    expect(hasA11yLabel(tree, "Your answer")).toBe(true);
  });

  it("re-reads the question id at submit time so a fallback answer resolves after a failed read", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const answerClarification = jest
      .fn()
      .mockResolvedValue(
        event({ id: "a", raw_text: "milk", status: "processing" }),
      );
    // The sheet-opening read fails (transient), so no question id is stashed on
    // the sheet target; the submit-time re-read succeeds.
    const getClarification = jest
      .fn()
      .mockRejectedValueOnce(new LogEventApiError(404, "We couldn't find your log."))
      .mockResolvedValue({
        questions: [{ id: "q1", text: "What kind of milk?", options: [] }],
      });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        answerClarification={answerClarification}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });
    typeInto(tree, "Your answer", "Oat milk");
    await act(async () => {
      press(tree, "Submit answer");
    });

    // The free-text fallback genuinely submits — never dropped on the floor: the
    // question id is re-read at submit time and the answer travels the round-trip.
    expect(getClarification).toHaveBeenCalledTimes(2);
    expect(answerClarification).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "a",
      "q1",
      "Oat milk",
    );
    expect(hasA11yLabel(tree, "milk, needs a detail, uncounted")).toBe(false);
  });

  it("surfaces the failure and keeps the row actionable when the submit-time re-read also fails", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const answerClarification = jest.fn();
    const getClarification = jest
      .fn()
      .mockRejectedValue(new LogEventApiError(404, "We couldn't find your log."));
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        answerClarification={answerClarification}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });
    typeInto(tree, "Your answer", "Oat milk");
    await act(async () => {
      press(tree, "Submit answer");
    });

    // Both reads failed: the failure is surfaced, nothing is submitted against a
    // fabricated id, and the row stays needs-a-detail — tappable, never a dead end.
    expect(answerClarification).not.toHaveBeenCalled();
    expect(textContent(tree)).toContain("We couldn't find your log.");
    expect(hasA11yLabel(tree, "milk, needs a detail, uncounted")).toBe(true);
  });

  it("surfaces an honest error when the event has no persisted question to answer", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const answerClarification = jest.fn();
    // Both the opening read and the submit-time re-read return an empty payload.
    const getClarification = emptyClarification();
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        answerClarification={answerClarification}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });
    typeInto(tree, "Your answer", "Oat milk");
    await act(async () => {
      press(tree, "Submit answer");
    });

    // No question exists server-side, so there is nothing to answer against:
    // say so plainly and leave the row actionable rather than dead-ending.
    expect(answerClarification).not.toHaveBeenCalled();
    expect(textContent(tree)).toContain(
      "We couldn't load the question. Reopen the entry and try again.",
    );
    expect(hasA11yLabel(tree, "milk, needs a detail, uncounted")).toBe(true);
  });
});

describe("TodayScreen failed-parse rows (FTY-176)", () => {
  it("renders a failed parse as an actionable Retry + Edit-as-text row, never static", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "asdfghjkl", status: "failed" }),
      ]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    // Calm inline copy, the captured text, and a visibly-uncounted row.
    const content = textContent(tree);
    expect(content).toContain("asdfghjkl");
    expect(content).toContain("Couldn't read that");
    // The failed state is conveyed to VoiceOver via the status icon.
    expect(hasA11yLabel(tree, "Estimate didn't finish")).toBe(true);
    // Both affordances are present and tappable — not a static dead-end row.
    expect(hasA11yLabel(tree, "Retry")).toBe(true);
    expect(hasA11yLabel(tree, "Edit as text")).toBe(true);
  });

  it("Retry re-submits the same text with a NEW idempotency key and swaps in a pending row", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "asdfghjkl", status: "failed" }),
      ]);
    const create = jest
      .fn()
      .mockResolvedValue(
        event({ id: "server-2", raw_text: "asdfghjkl", status: "pending" }),
      );
    const keys = sequentialKeys();
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        generateKey={keys}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "Retry");
    });

    // A genuine new attempt via the create path — same text, a fresh key.
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "asdfghjkl",
      expect.any(String),
    );
    // The failed row is superseded in place by the new pending attempt — no
    // stale duplicate, and it is now a waiting-to-estimate row.
    expect(hasA11yLabel(tree, "Retry")).toBe(false);
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
    expect(textContent(tree)).toContain("asdfghjkl");
  });

  it("Edit as text prefills the composer with the failed text and supersedes the row", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "asdfghjkl", status: "failed" }),
      ]);
    const create = jest
      .fn()
      .mockResolvedValue(
        event({ id: "server-2", raw_text: "an apple", status: "pending" }),
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

    act(() => {
      press(tree, "Edit as text");
    });

    // The failed text is now in the composer for the user to fix, and the row is
    // superseded in place (the text is safe in the composer, not lost).
    expect(inputValue(tree, "Log food or exercise")).toBe("asdfghjkl");
    expect(hasA11yLabel(tree, "Retry")).toBe(false);

    // Fixing the wording and submitting resubmits through the same create path.
    typeInto(tree, "Log food or exercise", "an apple");
    await act(async () => {
      press(tree, "Add entry");
    });
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "an apple",
      expect.any(String),
    );
  });

  it("a retry whose create call errors restores the actionable failed row and surfaces the error", async () => {
    jest.useFakeTimers();
    try {
      const load = jest
        .fn()
        .mockResolvedValue([
          event({ id: "a", raw_text: "asdfghjkl", status: "failed" }),
        ]);
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

      await act(async () => {
        press(tree, "Retry");
      });

      // The create failed: the optimistic attempt is rolled back, the original
      // failed row reappears (still actionable), and the failure is surfaced.
      expect(hasA11yLabel(tree, "Retry")).toBe(true);
      expect(hasA11yLabel(tree, "Edit as text")).toBe(true);
      expect(textContent(tree)).toContain("That entry couldn't be saved.");
    } finally {
      jest.useRealTimers();
    }
  });

  it("keeps the retried failed row hidden even after a poll re-fetches it as failed", async () => {
    jest.useFakeTimers();
    try {
      const load = jest
        .fn()
        // Initial load + every poll keep returning the original failed row.
        .mockResolvedValue([
          event({ id: "a", raw_text: "asdfghjkl", status: "failed" }),
        ]);
      const create = jest
        .fn()
        .mockResolvedValue(
          event({ id: "server-2", raw_text: "asdfghjkl", status: "pending" }),
        );
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          create={create}
          useActive={() => true}
          pollIntervalMs={1000}
        />,
      );
      await act(async () => {});

      await act(async () => {
        press(tree, "Retry");
      });

      // The fresh attempt is pending → polling runs and re-fetches the original
      // failed row; it must stay superseded (retried this session).
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});

      expect(hasA11yLabel(tree, "Retry")).toBe(false);
    } finally {
      jest.useRealTimers();
    }
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
        getClarification={emptyClarification()}
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
        getClarification={emptyClarification()}
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

// ─── Confirm-parsed-values sheet (FTY-197) ───────────────────────────────────

describe("TodayScreen confirm-parsed-values sheet", () => {
  const completedLabelEvent: LogEventDTO = {
    id: "label-event-1",
    user_id: SESSION!.userId,
    raw_text: "Nutrition label photo",
    status: "completed",
    created_at: "2026-07-02T10:00:00Z",
    updated_at: "2026-07-02T10:00:00Z",
  };

  function labelProposalItem(
    overrides: Partial<DerivedFoodItemDTO> = {},
  ): DerivedFoodItemDTO {
    return foodItem({
      id: "label-food-1",
      log_event_id: "label-event-1",
      name: "Granola bar",
      unit: "bar",
      status: "proposed",
      calories: 190,
      protein_g: 4,
      carbs_g: 29,
      fat_g: 7,
      source: { source_type: "user_label", label: "Label scan", ref: "user_label" },
      ...overrides,
    });
  }

  async function uploadLabel(tree: ReactTestRenderer): Promise<void> {
    press(tree, "Capture label");
    await act(async () => {
      press(tree, "Take photo");
    });
    await act(async () => {
      press(tree, "Upload label");
    });
    // Let the proposal read resolve and open the confirm sheet.
    await act(async () => {});
  }

  function labelProps(overrides: Record<string, unknown>) {
    return {
      session: SESSION,
      load: jest.fn().mockResolvedValue([]),
      useActive: INACTIVE,
      uploadLabel: jest.fn().mockResolvedValue(completedLabelEvent),
      labelTakePhoto: jest.fn().mockResolvedValue({ uri: "file:///label.jpg" }),
      ...overrides,
    };
  }

  it("shows the parsed values + Label scan provenance, not yet counted, after a legible upload", async () => {
    const getLabelProposal = jest.fn().mockResolvedValue(labelProposalItem());
    const tree = mount(<TodayScreen {...labelProps({ getLabelProposal })} />);
    await act(async () => {});

    await uploadLabel(tree);

    // The proposal read was made for the uploaded event.
    expect(getLabelProposal).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "label-event-1",
    );
    // The confirm sheet shows the parse, provenance, and the not-yet-counted state.
    const text = textContent(tree);
    expect(text).toContain("Granola bar");
    expect(text).toContain("190 kcal");
    expect(text).toContain("Label scan");
    expect(text).toContain("Not yet counted");
    expect(hasA11yLabel(tree, "Looks right, add it")).toBe(true);
  });

  it("confirm commits the parse and refreshes the day's totals in place", async () => {
    const getLabelProposal = jest.fn().mockResolvedValue(labelProposalItem());
    const confirmLabelProposal = jest
      .fn()
      .mockResolvedValue(labelProposalItem({ status: "resolved" }));
    // First summary load excludes the proposal; after confirm it counts.
    const getDailySummary = jest
      .fn()
      .mockResolvedValueOnce(summary({ intake: { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 }, has_intake: false }))
      .mockResolvedValue(summary({ intake: { calories: 190, protein_g: 4, carbs_g: 29, fat_g: 7 } }));

    const tree = mount(
      <TodayScreen
        {...labelProps({ getLabelProposal, confirmLabelProposal, getDailySummary })}
      />,
    );
    await act(async () => {});

    await uploadLabel(tree);
    await act(async () => {
      press(tree, "Looks right, add it");
    });

    // Confirm called with an empty (unchanged) body; summary refetched.
    expect(confirmLabelProposal).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "label-event-1",
      {},
    );
    // The entry now counts: the resolved item row shows the kcal (no "not counted").
    expect(hasA11yLabel(tree, "Granola bar, 190 kcal")).toBe(true);
    // Sheet dismissed — the confirm affordance is gone (in-place, no navigation).
    expect(hasA11yLabel(tree, "Looks right, add it")).toBe(false);
  });

  it("adjusting a value sends the corrected number to the confirm action", async () => {
    const getLabelProposal = jest.fn().mockResolvedValue(labelProposalItem());
    const confirmLabelProposal = jest
      .fn()
      .mockResolvedValue(labelProposalItem({ status: "resolved", calories: 250 }));
    const tree = mount(
      <TodayScreen {...labelProps({ getLabelProposal, confirmLabelProposal })} />,
    );
    await act(async () => {});

    await uploadLabel(tree);
    press(tree, "Adjust values");
    typeInto(tree, "Calories value", "250");
    await act(async () => {
      press(tree, "Add adjusted values");
    });

    expect(confirmLabelProposal).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "label-event-1",
      { calories: 250 },
    );
  });

  it("never silently counts: dismissing leaves an uncounted proposal, re-openable", async () => {
    const getLabelProposal = jest.fn().mockResolvedValue(labelProposalItem());
    const confirmLabelProposal = jest.fn();
    const tree = mount(
      <TodayScreen {...labelProps({ getLabelProposal, confirmLabelProposal })} />,
    );
    await act(async () => {});

    await uploadLabel(tree);
    // Dismiss without confirming.
    press(tree, "Close");

    expect(confirmLabelProposal).not.toHaveBeenCalled();
    // The proposal is honestly surfaced in the timeline as "not yet counted".
    expect(
      tree.root.findAll(
        (n) => n.props.accessibilityLabel === "Granola bar, 190 kcal, not yet counted",
      ).length,
    ).toBeGreaterThan(0);
  });

  it("leaves the unreadable path unchanged when there is no proposal", async () => {
    // A not-a-label / unreadable disposition yields a null proposal.
    const getLabelProposal = jest.fn().mockResolvedValue(null);
    const failedEvent: LogEventDTO = { ...completedLabelEvent, status: "failed" };
    const tree = mount(
      <TodayScreen
        {...labelProps({
          getLabelProposal,
          uploadLabel: jest.fn().mockResolvedValue(failedEvent),
        })}
      />,
    );
    await act(async () => {});

    await uploadLabel(tree);

    // No confirm sheet is presented for a null proposal.
    expect(hasA11yLabel(tree, "Looks right, add it")).toBe(false);
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
      expect.any(String),
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

// ─── Consolidated logging on Today (FTY-147) ─────────────────────────────────

describe("TodayScreen composer — calm, status-first", () => {
  it("does not auto-focus the composer on mount (Today is the status-home)", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    const input = tree.root.find(
      (n) => n.props.accessibilityLabel === "Log food or exercise",
    );
    // Auto-raising the keyboard on a dashboard is jarring (Calm by default).
    expect(input.props.autoFocus).toBeFalsy();
  });

  it("acknowledges a submit in the single timeline — no separate 'added this session' feed", async () => {
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
        getClarification={emptyClarification()}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "greek yogurt");
    press(tree, "Add entry");

    // Immediate acknowledgement in the canonical timeline; composer cleared.
    expect(textContent(tree)).toContain("greek yogurt");
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
    expect(inputValue(tree, "Log food or exercise")).toBe("");
    // There is exactly one timeline — no harvested "Added this session" feed.
    expect(textContent(tree)).not.toContain("Added this session");

    await act(async () => {
      resolveCreate(
        event({ id: "server-1", raw_text: "greek yogurt", status: "completed" }),
      );
    });
    expect(textContent(tree)).toContain("greek yogurt");
  });
});

describe("TodayScreen offline-queue logging", () => {
  it("queues an unreachable submit as a dedicated OfflineEntryRow + banner, never blocking", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const create = jest.fn().mockRejectedValue(networkError());
    const { store, data } = memoryStore();
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        useActive={INACTIVE}
        outboxStore={store}
        generateKey={sequentialKeys()}
        now={() => "2026-06-28T08:00:00.000Z"}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "two eggs");
    await act(async () => {
      press(tree, "Add entry");
    });

    // Capture was not blocked: composer stays mounted and the input cleared.
    expect(hasA11yLabel(tree, "Log food or exercise")).toBe(true);
    expect(inputValue(tree, "Log food or exercise")).toBe("");

    // The capture renders as a dedicated offline row (in words), uncounted.
    expect(hasA11yLabel(tree, "two eggs, offline, queued to send")).toBe(true);
    // The calm connection banner reflects the offline + queued state.
    expect(textContent(tree)).toContain("Offline");
    expect(textContent(tree)).toContain("1 entry queued");

    // It is durably persisted with the stable idempotency key.
    expect(data.get(SESSION!.userId)).toEqual([
      {
        idempotencyKey: "key-0",
        userId: SESSION!.userId,
        rawText: "two eggs",
        capturedAt: "2026-06-28T08:00:00.000Z",
        syncState: "queued",
      },
    ]);
  });

  it("does not render the offline capture through EntryRow's status placeholder", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const create = jest.fn().mockRejectedValue(networkError());
    const { store } = memoryStore();
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        useActive={INACTIVE}
        outboxStore={store}
        generateKey={sequentialKeys()}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "two eggs");
    await act(async () => {
      press(tree, "Add entry");
    });

    // The dedicated offline row is present…
    expect(hasA11yLabel(tree, "two eggs, offline, queued to send")).toBe(true);
    // …and the offline capture is NOT rendered as a pending EntryRow (which would
    // read "Waiting to estimate"). The offline row owns the offline state.
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(false);
  });

  it("drains the outbox on reconnect; the capture folds into the normal pending flow", async () => {
    jest.useFakeTimers();
    try {
      const load = jest.fn().mockResolvedValue([]);
      const serverEvent = event({
        id: "server-1",
        raw_text: "two eggs",
        status: "pending",
      });
      // Online attempt fails unreachable; the reconnect drain succeeds.
      const create = jest
        .fn()
        .mockRejectedValueOnce(networkError())
        .mockResolvedValue(serverEvent);
      const { store } = memoryStore();
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          create={create}
          useActive={INACTIVE}
          outboxStore={store}
          generateKey={sequentialKeys()}
          now={() => "2026-06-28T08:00:00.000Z"}
          retryIntervalMs={1000}
        />,
      );
      await act(async () => {});

      typeInto(tree, "Log food or exercise", "two eggs");
      await act(async () => {
        press(tree, "Add entry");
      });
      expect(hasA11yLabel(tree, "two eggs, offline, queued to send")).toBe(true);

      // Reconnect probe fires: the drain re-submits with the SAME key.
      await act(async () => {
        jest.advanceTimersByTime(1000);
      });

      // The drain re-submitted with the SAME idempotency key minted at capture.
      const lastCall = create.mock.calls[create.mock.calls.length - 1];
      expect(lastCall[1]).toBe("two eggs");
      expect(lastCall[2]).toBe("key-0");
      // The entry left the offline queue and now follows the normal pending flow.
      expect(hasA11yLabel(tree, "two eggs, offline, queued to send")).toBe(false);
      expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });
});

describe("TodayScreen timeline timestamps (FTY-174 / audit A6)", () => {
  it("renders a known morning entry with the correct AM meridiem, never PM", async () => {
    // The exact regression: an 11:14 AM local instant must show "11:14 AM" in the
    // real timeline cluster header — not "11:14 PM" (the observed Hermes bug).
    //
    // Build the instant from *local* wall-clock components (11:14 on the machine's
    // own zone) so the assertion is deterministic on any CI timezone: the header
    // renders in the device zone, so it must read back the same 11:14 AM. The
    // stored `created_at` is that instant serialized to UTC, exactly as the
    // tz-aware backend (FTY-173) would send it.
    const localMorning = new Date(2026, 5, 27, 11, 14, 0); // 11:14 AM, device zone
    const load = jest.fn().mockResolvedValue([
      event({
        id: "morning",
        raw_text: "Oatmeal",
        status: "completed",
        created_at: localMorning.toISOString(),
      }),
    ]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    const content = textContent(tree);
    expect(content).toContain("Oatmeal");
    expect(content).toContain("11:14 AM");
    expect(content).not.toContain("11:14 PM");
  });
});
