import { act } from "react-test-renderer";

import { TodayScreen } from "./TodayScreen";
import {
  LogEventApiError,
  type LogEventDTO,
} from "@/api/logEvents";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

import {
  INACTIVE,
  SESSION,
  cleanupTrees,
  event,
  hasA11yLabel,
  inputValue,
  memoryStore,
  mount,
  networkError,
  press,
  savedFood,
  sequentialKeys,
  summary,
  textContent,
  typeInto,
} from "./today/todayTestUtils";

// The beat haptics are mocked so transitions can be asserted through the real
// screen without a native Taptic Engine, and so a resolve/save/target beat
// firing in these suites never reaches a real (unsupported) native call.
jest.mock("@/theme/haptics", () => ({
  entryResolvedHaptic: jest.fn(),
  correctionSavedHaptic: jest.fn(),
  targetReachedHaptic: jest.fn(),
}));

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

jest.mock("expo-camera", () => ({
  useCameraPermissions: jest.fn(() => [
    { status: "granted", granted: true, canAskAgain: false, expires: "never" },
    jest.fn().mockResolvedValue({ status: "granted", granted: true }),
    jest.fn().mockResolvedValue({ status: "granted", granted: true }),
  ]),
  CameraView: jest.fn(() => null),
}));

jest.mock("expo-linking", () => ({
  openSettings: jest.fn().mockResolvedValue(undefined),
}));

// The item-forward by-date feed (FTY-198) is read from a real endpoint by
// default (FTY-180). Stub it to an empty day so tests that don't exercise item
// rows stay hermetic — no real fetch — while tests that do pass an explicit
// `loadEntries` prop that overrides this default.
jest.mock("@/api/logEvents", () => {
  const actual = jest.requireActual("@/api/logEvents");
  return {
    ...actual,
    listTodayLogEventEntries: jest.fn().mockResolvedValue([]),
  };
});

beforeEach(() => mockReduceMotion(false));

afterEach(cleanupTrees);

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

    // Normal entry created; no synthetic item, so it renders the pending
    // skeleton (FTY-180), not its raw text.
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "banana",
      expect.any(String),
    );
    expect(textContent(tree)).not.toContain("banana");
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
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
