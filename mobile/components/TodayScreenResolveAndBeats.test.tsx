import { act, type ReactTestRenderer } from "react-test-renderer";

import { TodayScreen } from "./TodayScreen";
import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import {
  type LogEventDTO,
  type LogEventEntryDTO,
} from "@/api/logEvents";
import { mockReduceMotion } from "@/testUtils/reduceMotion";
import { entryResolvedHaptic, targetReachedHaptic } from "@/theme/haptics";

import {
  INACTIVE,
  SESSION,
  cleanupTrees,
  event,
  foodItem,
  hasA11yLabel,
  mount,
  press,
  summary,
  textContent,
} from "./today/todayTestUtils";

// The beat haptics are mocked so transitions can be asserted through the real
// screen without a native Taptic Engine, and so a resolve/save/target beat
// firing in these suites never reaches a real (unsupported) native call.
jest.mock("@/theme/haptics", () => ({
  entryResolvedHaptic: jest.fn(),
  correctionSavedHaptic: jest.fn(),
  targetReachedHaptic: jest.fn(),
}));

const mockEntryResolvedHaptic = entryResolvedHaptic as jest.MockedFunction<
  typeof entryResolvedHaptic
>;
const mockTargetReachedHaptic = targetReachedHaptic as jest.MockedFunction<
  typeof targetReachedHaptic
>;

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

beforeEach(() => {
  mockReduceMotion(false);
  mockEntryResolvedHaptic.mockClear();
  mockTargetReachedHaptic.mockClear();
});

afterEach(cleanupTrees);

describe("TodayScreen resolve in place (FTY-180)", () => {
  function entry(
    e: LogEventDTO,
    items: readonly DerivedFoodItemDTO[] = [],
  ): LogEventEntryDTO {
    return { event: e, items };
  }

  // RN wraps hosts in several forwardRef composites, so an absolute node count is
  // brittle. `hasProgressbar` is a robust presence check; its absence (=== 0) is
  // the clean signal that the pending skeleton is fully gone after a resolve.
  const hasProgressbar = (tree: ReactTestRenderer): boolean =>
    tree.root.findAll((n) => n.props.accessibilityRole === "progressbar").length >
    0;

  it("populates a completed entry's value rows from the real by-date feed (not the items prop)", async () => {
    const completed = event({ id: "a", raw_text: "Greek yogurt", status: "completed" });
    const load = jest.fn().mockResolvedValue([completed]);
    // The value rows come only from the item-forward feed — no `items` override.
    const loadEntries = jest
      .fn()
      .mockResolvedValue([entry(completed, [foodItem()])]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        loadEntries={loadEntries}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    expect(loadEntries).toHaveBeenCalled();
    expect(textContent(tree)).toContain("Greek yogurt");
    expect(textContent(tree)).toContain("150 kcal");
  });

  it("resolves the pending skeleton into the value row in place on the pending→completed poll", async () => {
    jest.useFakeTimers();
    try {
      const pending = event({ id: "a", raw_text: "Greek yogurt", status: "pending" });
      const completed = event({ id: "a", raw_text: "Greek yogurt", status: "completed" });
      const load = jest
        .fn()
        .mockResolvedValueOnce([pending])
        .mockResolvedValueOnce([completed]);
      // The feed reports no items while pending, then the resolved item once done.
      const loadEntries = jest
        .fn()
        .mockResolvedValueOnce([entry(pending, [])])
        .mockResolvedValueOnce([entry(completed, [foodItem()])]);
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          loadEntries={loadEntries}
          useActive={() => true}
          pollIntervalMs={1000}
        />,
      );
      await act(async () => {});

      // Pending: the shimmer skeleton, no value, no raw phrase.
      expect(hasProgressbar(tree)).toBe(true);
      expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
      expect(textContent(tree)).not.toContain("150 kcal");

      // One poll later the entry is completed and its item feed has the value.
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});

      // The skeleton is fully gone (no lingering placeholder) and the resolved
      // value row is now shown — the same row resolved in place (the shared-key
      // instance-preservation is unit-tested in ItemTimelineRow.test.tsx).
      expect(hasProgressbar(tree)).toBe(false);
      expect(hasA11yLabel(tree, "Greek yogurt, 150 kcal")).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });

  it("restores secondary item rows after a multi-item completion resolves from a pending skeleton", async () => {
    jest.useFakeTimers();
    try {
      const pending = event({ id: "a", raw_text: "Greek yogurt and banana", status: "pending" });
      const completed = event({
        id: "a",
        raw_text: "Greek yogurt and banana",
        status: "completed",
      });
      const banana = foodItem({
        id: "item-b",
        name: "Banana",
        calories: 105,
      });
      const load = jest
        .fn()
        .mockResolvedValueOnce([pending])
        .mockResolvedValueOnce([completed]);
      const loadEntries = jest
        .fn()
        .mockResolvedValueOnce([entry(pending, [])])
        .mockResolvedValueOnce([entry(completed, [foodItem(), banana])]);
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          loadEntries={loadEntries}
          useActive={() => true}
          pollIntervalMs={1000}
        />,
      );
      await act(async () => {});

      expect(hasProgressbar(tree)).toBe(true);
      expect(textContent(tree)).not.toContain("Greek yogurt and banana");

      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});

      expect(hasProgressbar(tree)).toBe(false);

      act(() => jest.advanceTimersByTime(200));
      await act(async () => {});

      expect(hasA11yLabel(tree, "Greek yogurt, 150 kcal")).toBe(true);
      expect(hasA11yLabel(tree, "Banana, 105 kcal")).toBe(true);
      expect(textContent(tree)).toContain("Banana");

      press(tree, "Banana, 105 kcal");
      expect(hasA11yLabel(tree, "Increase amount")).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });

  it("holds the skeleton (never an EntryRow placeholder) when the event-list poll resolves completed before the by-date feed populates items", async () => {
    // Race: within one poll the event-list read resolves the entry to `completed`
    // a microtask before the by-date item feed folds its value rows into
    // `itemsByEvent`. In that intermediate render the row must stay the same
    // loading ItemTimelineRow — never fall through to the raw-text EntryRow
    // placeholder — so the pending→resolved transition is one in-place fade with
    // zero layout shift (FTY-180 review). Resolving the two reads in a controlled
    // order reproduces the exact interleave.
    jest.useFakeTimers();
    try {
      const pending = event({
        id: "a",
        raw_text: "grilled cheese sandwich",
        status: "pending",
      });
      const completed = event({
        id: "a",
        raw_text: "grilled cheese sandwich",
        status: "completed",
      });
      let resolveLoad!: (events: readonly LogEventDTO[]) => void;
      const load = jest
        .fn()
        .mockResolvedValueOnce([pending])
        .mockReturnValueOnce(
          new Promise((resolve) => {
            resolveLoad = resolve;
          }),
        )
        .mockResolvedValue([completed]);
      const loadEntries = jest
        .fn()
        .mockResolvedValueOnce([entry(pending, [])])
        .mockReturnValueOnce(new Promise<readonly LogEventEntryDTO[]>(() => null))
        .mockResolvedValue([entry(completed, [foodItem()])]);
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          loadEntries={loadEntries}
          useActive={() => true}
          pollIntervalMs={1000}
        />,
      );
      await act(async () => {});

      // Pending: shimmer skeleton, no value, no raw phrase.
      expect(hasProgressbar(tree)).toBe(true);
      expect(textContent(tree)).not.toContain("grilled cheese sandwich");

      // Poll fires both reads. The event-list read wins the race: the entry is
      // now completed but its items have NOT arrived yet. The row must remain the
      // loading skeleton — not the raw-text EntryRow — with no value.
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {
        resolveLoad([completed]);
      });
      expect(hasProgressbar(tree)).toBe(true);
      expect(textContent(tree)).not.toContain("grilled cheese sandwich");
      expect(textContent(tree)).not.toContain("150 kcal");

      // Even past the fade window, the row holds shared geometry until items arrive.
      act(() => jest.advanceTimersByTime(200));
      await act(async () => {});
      expect(hasProgressbar(tree)).toBe(true);
      expect(textContent(tree)).not.toContain("grilled cheese sandwich");
      expect(textContent(tree)).not.toContain("150 kcal");

      expect(loadEntries).toHaveBeenCalledTimes(2);
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});
      expect(loadEntries).toHaveBeenCalledTimes(3);
      expect(hasProgressbar(tree)).toBe(false);
      expect(hasA11yLabel(tree, "Greek yogurt, 150 kcal")).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });

  it("holds the skeleton (no un-animated value swap) if the item feed wins the poll race before the event completes", async () => {
    // Race: the by-date feed already carries the resolved item while the event
    // list still reports the event as pending. The value row must NOT surface
    // through the optimistic fallback — it waits for the completed branch so the
    // resolve always animates in place (FTY-180).
    const pending = event({ id: "a", raw_text: "Greek yogurt", status: "pending" });
    const load = jest.fn().mockResolvedValue([pending]);
    const loadEntries = jest
      .fn()
      .mockResolvedValue([entry(pending, [foodItem()])]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        loadEntries={loadEntries}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    expect(hasProgressbar(tree)).toBe(true);
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
    expect(textContent(tree)).not.toContain("150 kcal");
    expect(hasA11yLabel(tree, "Greek yogurt, 150 kcal")).toBe(false);
  });
});

describe("TodayScreen — beat 1: entry resolve (FTY-181)", () => {
  it("does not fire on initial load of an already-completed entry (no beat on mount)", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "Oatmeal", status: "completed" }),
      ]);
    mount(<TodayScreen session={SESSION} load={load} useActive={INACTIVE} />);
    await act(async () => {});
    expect(mockEntryResolvedHaptic).not.toHaveBeenCalled();
  });

  it("fires once when a pending entry resolves to completed on a poll", async () => {
    jest.useFakeTimers();
    try {
      const pending = event({ id: "a", raw_text: "Oatmeal", status: "pending" });
      const completed = event({
        id: "a",
        raw_text: "Oatmeal",
        status: "completed",
      });
      // First load: pending (nothing resolved yet). Every poll after: completed.
      const load = jest
        .fn()
        .mockResolvedValueOnce([pending])
        .mockResolvedValue([completed]);
      mount(
        <TodayScreen
          session={SESSION}
          load={load}
          useActive={() => true}
          pollIntervalMs={1000}
        />,
      );
      await act(async () => {});
      // Seeded on the pending load — no resolve yet.
      expect(mockEntryResolvedHaptic).not.toHaveBeenCalled();

      // Poll reconciles the same event as completed → the resolve beat fires once.
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});
      expect(mockEntryResolvedHaptic).toHaveBeenCalledTimes(1);

      // A further poll returning the same completed event must not re-fire.
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});
      expect(mockEntryResolvedHaptic).toHaveBeenCalledTimes(1);
    } finally {
      jest.useRealTimers();
    }
  });

  it("eases in the resolved value row from the real by-date item feed (not injected items)", async () => {
    jest.useFakeTimers();
    try {
      // The value row's data comes from the item-forward by-date feed (FTY-198),
      // NOT the injectable `items` prop — this is the real screen data path the
      // reviewer flagged as unwired. First load: the entry is pending and the feed
      // has no items. On the poll it resolves and the feed carries its derived
      // item, so the resolved value row renders and the entry-resolve beat fires.
      const pending = event({ id: "a", raw_text: "Yogurt", status: "pending" });
      const completed = event({ id: "a", raw_text: "Yogurt", status: "completed" });
      const load = jest
        .fn()
        .mockResolvedValueOnce([pending])
        .mockResolvedValue([completed]);
      const loadEntries = jest
        .fn()
        .mockResolvedValueOnce([{ event: pending, items: [] }])
        .mockResolvedValue([{ event: completed, items: [foodItem()] }]);
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          loadEntries={loadEntries}
          useActive={() => true}
          pollIntervalMs={1000}
        />,
      );
      await act(async () => {});
      // Pending: no value row yet, and no beat.
      expect(hasA11yLabel(tree, "Greek yogurt, 150 kcal")).toBe(false);
      expect(mockEntryResolvedHaptic).not.toHaveBeenCalled();

      // Poll: the event completes and the feed supplies its item → the resolved
      // value row is now on-screen, sourced entirely from the server feed.
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});
      expect(hasA11yLabel(tree, "Greek yogurt, 150 kcal")).toBe(true);
      expect(mockEntryResolvedHaptic).toHaveBeenCalledTimes(1);
    } finally {
      jest.useRealTimers();
    }
  });

  it("does not render a server-fed value row while the event list still has the entry pending (no un-animated resolve)", async () => {
    jest.useFakeTimers();
    try {
      // The race the reviewer flagged: the by-date feed reports the entry
      // completed-with-items while the event-list poll lags (or failed) and
      // still holds it pending. The resolved value row must NOT render through
      // the saved-food fallback — it can only surface once the event-list poll
      // reconciles the entry to completed, so beat 1 fires on that transition
      // instead of a row appearing un-animated (FTY-181 review).
      const pending = event({ id: "a", raw_text: "Yogurt", status: "pending" });
      const completed = event({ id: "a", raw_text: "Yogurt", status: "completed" });
      // Event list lags on the first two loads, only catching up on the third.
      const load = jest
        .fn()
        .mockResolvedValueOnce([pending])
        .mockResolvedValueOnce([pending])
        .mockResolvedValue([completed]);
      // The by-date feed already reports the entry completed-with-items from the
      // very first read — it won the race.
      const loadEntries = jest
        .fn()
        .mockResolvedValue([{ event: completed, items: [foodItem()] }]);
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          loadEntries={loadEntries}
          useActive={() => true}
          pollIntervalMs={1000}
        />,
      );
      await act(async () => {});
      // Feed already has the item, but the event is pending → no value row, no beat.
      expect(hasA11yLabel(tree, "Greek yogurt, 150 kcal")).toBe(false);
      expect(mockEntryResolvedHaptic).not.toHaveBeenCalled();

      // A poll where the event list still lags must not leak the row or a beat.
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});
      expect(hasA11yLabel(tree, "Greek yogurt, 150 kcal")).toBe(false);
      expect(mockEntryResolvedHaptic).not.toHaveBeenCalled();

      // The event list catches up → the row renders and the resolve beat fires once.
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});
      expect(hasA11yLabel(tree, "Greek yogurt, 150 kcal")).toBe(true);
      expect(mockEntryResolvedHaptic).toHaveBeenCalledTimes(1);
    } finally {
      jest.useRealTimers();
    }
  });

  it("fires once per event when two pending entries resolve in the same reconciliation", async () => {
    jest.useFakeTimers();
    try {
      // Two entries are pending on the first load, then both reconcile to
      // completed in the SAME poll batch. The resolve beat is once-per-event, so
      // a batch of two fresh completions must fire two soft taps — not one tap
      // coalesced across the batch (FTY-181 review).
      const pendingA = event({ id: "a", raw_text: "Oatmeal", status: "pending" });
      const pendingB = event({ id: "b", raw_text: "Yogurt", status: "pending" });
      const completedA = event({ id: "a", raw_text: "Oatmeal", status: "completed" });
      const completedB = event({ id: "b", raw_text: "Yogurt", status: "completed" });
      const load = jest
        .fn()
        .mockResolvedValueOnce([pendingA, pendingB])
        .mockResolvedValue([completedA, completedB]);
      mount(
        <TodayScreen
          session={SESSION}
          load={load}
          useActive={() => true}
          pollIntervalMs={1000}
        />,
      );
      await act(async () => {});
      // Both seeded pending on the first load — nothing resolved yet.
      expect(mockEntryResolvedHaptic).not.toHaveBeenCalled();

      // One poll reconciles BOTH entries to completed at once → two beats.
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});
      expect(mockEntryResolvedHaptic).toHaveBeenCalledTimes(2);

      // A further poll returning the same completed pair must not re-fire.
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});
      expect(mockEntryResolvedHaptic).toHaveBeenCalledTimes(2);
    } finally {
      jest.useRealTimers();
    }
  });
});

describe("TodayScreen — beat 3: target reached through the real screen (FTY-181)", () => {
  it("fires the target-reached beat when a summary poll crosses the calorie target", async () => {
    jest.useFakeTimers();
    try {
      // A pending event keeps polling active; the summary crosses the target on
      // the poll (under budget → over budget) so the mounted hero beats once.
      const load = jest
        .fn()
        .mockResolvedValue([event({ id: "a", raw_text: "Oatmeal", status: "pending" })]);
      const getDailySummary = jest
        .fn()
        .mockResolvedValueOnce(
          summary({ intake: { calories: 1600, protein_g: 70, carbs_g: 120, fat_g: 40 } }),
        )
        .mockResolvedValue(
          summary({ intake: { calories: 2100, protein_g: 90, carbs_g: 160, fat_g: 55 } }),
        );
      mount(
        <TodayScreen
          session={SESSION}
          load={load}
          getDailySummary={getDailySummary}
          useActive={() => true}
          pollIntervalMs={1000}
        />,
      );
      await act(async () => {});
      // Seeded under budget on the first summary — no beat yet.
      expect(mockTargetReachedHaptic).not.toHaveBeenCalled();

      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});
      expect(mockTargetReachedHaptic).toHaveBeenCalledTimes(1);
    } finally {
      jest.useRealTimers();
    }
  });
});
