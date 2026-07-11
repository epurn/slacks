import { act } from "react-test-renderer";

import { TodayScreen } from "./TodayScreen";
import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import type { LogEventDTO, LogEventEntryDTO } from "@/api/logEvents";
import { toApiSession } from "@/state/session";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

import {
  INACTIVE,
  SESSION,
  cleanupTrees,
  event,
  foodItem,
  hasA11yLabel,
  mount,
  networkError,
  press,
  summary,
  textContent,
} from "./today/todayTestUtils";

// Haptics are native; stub so a resolve/save beat firing under the real screen
// never reaches a native call.
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
    SymbolView: ({
      name,
      accessibilityLabel,
    }: {
      name: string;
      accessibilityLabel?: string;
    }) =>
      ReactLib.createElement(ReactNative.View, {
        testID: `sf-symbol-${String(name)}`,
        accessibilityLabel,
      }),
  };
});

jest.mock("expo-camera", () => ({
  useCameraPermissions: jest.fn(() => [
    { status: "granted", granted: true, canAskAgain: false, expires: "never" },
    jest.fn(),
    jest.fn(),
  ]),
  CameraView: jest.fn(() => null),
}));

jest.mock("expo-linking", () => ({
  openSettings: jest.fn().mockResolvedValue(undefined),
}));

beforeEach(() => mockReduceMotion(false));
afterEach(cleanupTrees);

function entry(
  e: LogEventDTO,
  items: readonly DerivedFoodItemDTO[] = [],
): LogEventEntryDTO {
  return { event: e, items };
}

const API_SESSION = toApiSession(SESSION!);

/** A completed "Greek yogurt" entry with one resolved 150-kcal item. */
function completedWithItem() {
  const completed = event({ id: "a", raw_text: "Greek yogurt", status: "completed" });
  return {
    completed,
    load: jest.fn().mockResolvedValue([completed]),
    loadEntries: jest.fn().mockResolvedValue([entry(completed, [foodItem()])]),
  };
}

describe("TodayScreen swipe-to-delete (FTY-322)", () => {
  it("removes the row optimistically, deletes the event, and refreshes totals", async () => {
    const { load, loadEntries } = completedWithItem();
    const deleteEvent = jest.fn().mockResolvedValue(undefined);
    const getDailySummary = jest
      .fn()
      .mockResolvedValueOnce(summary({ intake: { calories: 150, protein_g: 20, carbs_g: 8, fat_g: 4 } }))
      .mockResolvedValue(summary({ intake: { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 } }));

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        loadEntries={loadEntries}
        deleteEvent={deleteEvent}
        getDailySummary={getDailySummary}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});
    expect(textContent(tree)).toContain("Greek yogurt");

    // Reveal + tap Delete (the swipe reveal's destructive button).
    press(tree, "Delete Greek yogurt");
    await act(async () => {});

    // The event is soft-voided by id, the row leaves the timeline, and the day
    // totals refetch in place (the hero drops to zero).
    expect(deleteEvent).toHaveBeenCalledWith(API_SESSION, "a");
    expect(textContent(tree)).not.toContain("Greek yogurt");
    expect(getDailySummary.mock.calls.length).toBeGreaterThanOrEqual(2);
  });

  it("restores the row and shows a calm inline error when the delete fails", async () => {
    const { load, loadEntries } = completedWithItem();
    const deleteEvent = jest.fn().mockRejectedValue(networkError());
    const getDailySummary = jest.fn().mockResolvedValue(summary());

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        loadEntries={loadEntries}
        deleteEvent={deleteEvent}
        getDailySummary={getDailySummary}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    press(tree, "Delete Greek yogurt");
    await act(async () => {});

    // The row comes back (no silent loss) and a calm inline error appears.
    expect(textContent(tree)).toContain("Greek yogurt");
    expect(textContent(tree)).toContain("We couldn't delete that entry");
    const errorNode = tree.root.findAll(
      (n) =>
        n.props.testID === "today-delete-error" &&
        n.props.accessibilityRole === "alert",
    );
    expect(errorNode.length).toBeGreaterThanOrEqual(1);
  });

  it("does not resurrect a deleted row when a later poll still lists it", async () => {
    jest.useFakeTimers();
    try {
      const completed = event({ id: "a", raw_text: "Greek yogurt", status: "completed" });
      const pending = event({ id: "b", raw_text: "Cold brew", status: "pending" });
      // Every list (initial + each poll) still carries the completed event — the
      // race the guard must survive: the void hasn't propagated to this read yet.
      const load = jest.fn().mockResolvedValue([completed, pending]);
      const loadEntries = jest
        .fn()
        .mockResolvedValue([entry(completed, [foodItem()])]);
      const deleteEvent = jest.fn().mockResolvedValue(undefined);
      const getDailySummary = jest.fn().mockResolvedValue(summary());

      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          loadEntries={loadEntries}
          deleteEvent={deleteEvent}
          getDailySummary={getDailySummary}
          useActive={() => true}
          pollIntervalMs={1000}
        />,
      );
      await act(async () => {});
      expect(textContent(tree)).toContain("Greek yogurt");

      press(tree, "Delete Greek yogurt");
      await act(async () => {});
      expect(textContent(tree)).not.toContain("Greek yogurt");

      // A poll re-lists the still-present event; the row must stay gone while the
      // pending sibling keeps rendering (polling continues).
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});
      expect(textContent(tree)).not.toContain("Greek yogurt");
      expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });

  it("deletes via the VoiceOver custom action without the swipe gesture", async () => {
    const { load, loadEntries } = completedWithItem();
    const deleteEvent = jest.fn().mockResolvedValue(undefined);
    const getDailySummary = jest.fn().mockResolvedValue(summary());

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        loadEntries={loadEntries}
        deleteEvent={deleteEvent}
        getDailySummary={getDailySummary}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // The row exposes a Delete custom action on its own accessible element.
    const row = tree.root.find(
      (n) =>
        Array.isArray(n.props.accessibilityActions) &&
        n.props.accessibilityActions.some(
          (a: { name: string }) => a.name === "delete",
        ) &&
        typeof n.props.onAccessibilityAction === "function",
    );
    act(() =>
      row.props.onAccessibilityAction({ nativeEvent: { actionName: "delete" } }),
    );
    await act(async () => {});

    expect(deleteEvent).toHaveBeenCalledWith(API_SESSION, "a");
    expect(textContent(tree)).not.toContain("Greek yogurt");
  });
});
