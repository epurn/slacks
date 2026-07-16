/**
 * FTY-365: Trends refetches on focus so deletes (and new logs) are reflected.
 *
 * The Trends tab stays mounted across tab switches, so without a focus
 * subscription the adherence data loaded at first mount was served stale
 * forever — a void-delete on Today (FTY-322) never appeared. These tests
 * drive the injectable `useActive` focus seam (the FTY-341 idiom Today's
 * quick-add tests use) through blur → focus edges and assert:
 *
 * - one refetch per focus gain, reflecting a deletion in the strip/headline;
 * - the date window derives from the time of focus (day rollover shifts it);
 * - no refetch loop while the screen stays focused;
 * - the refresh is in place — settled content stays visible while the
 *   focus-triggered read is in flight (no unmount-to-skeleton swap).
 *
 * Sibling file to TrendsScreen.test.tsx (pinned at its LOC baseline), same
 * mount idioms.
 */

import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { TrendsScreen } from "@/components/TrendsScreen";
import type { DailySummaryDTO, TargetReadModel } from "@/api/dailySummary";
import type { Session } from "@/state/session";
import { rangeBounds } from "@/state/trends";
import { formatDate } from "@/state/weightEntries";

// TrendsScreen uses ScreenHeader → AppIcon (expo-symbols); stub the native
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

const SESSION: Session = {
  serverUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

const NOW = new Date("2026-06-27T12:00:00Z");
const TODAY = formatDate(NOW);
const YESTERDAY = formatDate(new Date(NOW.getTime() - 24 * 60 * 60 * 1000));

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
    uncounted_entries: 0,
    target: targetCal !== null ? makeTarget(targetCal) : null,
    exercise: { active_calories: 0 },
  };
}

function textContent(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

function skeletonCount(tree: ReactTestRenderer): number {
  return tree.root.findAll((n) => n.props.testID === "adherence-loading").length;
}

/** The strip cell for `date` (carries the human-readable adherence state). */
function cellLabel(tree: ReactTestRenderer, date: string): string {
  return tree.root.find((n) => n.props.testID === `adherence-cell-${date}`)
    .props.accessibilityLabel as string;
}

/**
 * A focus/clock harness around one mounted TrendsScreen. The `useActive` and
 * `now` props read mutable harness state, and every render uses a freshly
 * created element with the same (referentially stable) props, so a blur →
 * focus edge is exactly a prop-stable re-render pair — the way the navigator
 * delivers it — with no remount and no dependency churn.
 */
function mountHarness({
  getDailySummaryRange,
  listWeightEntries = jest.fn().mockResolvedValue([]),
}: {
  getDailySummaryRange: jest.Mock;
  listWeightEntries?: jest.Mock;
}) {
  let active = true;
  let current = NOW;
  const useActive = () => active;
  const now = () => current;

  const element = () => (
    <SafeAreaProvider
      initialMetrics={{
        frame: { x: 0, y: 0, width: 390, height: 844 },
        insets: { top: 47, left: 0, right: 0, bottom: 34 },
      }}
    >
      <TrendsScreen
        session={SESSION}
        listWeightEntries={listWeightEntries as never}
        getDailySummaryRange={getDailySummaryRange as never}
        now={now}
        useActive={useActive}
      />
    </SafeAreaProvider>
  );

  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(element());
  });

  return {
    tree,
    setClock(date: Date) {
      current = date;
    },
    rerender() {
      act(() => tree.update(element()));
    },
    blur() {
      active = false;
      act(() => tree.update(element()));
    },
    focus() {
      active = true;
      act(() => tree.update(element()));
    },
  };
}

const trees: ReactTestRenderer[] = [];
afterEach(() => {
  for (const tree of trees.splice(0)) {
    act(() => tree.unmount());
  }
});

describe("TrendsScreen focus refresh (FTY-365)", () => {
  it("refetches once per focus gain and reflects a deletion in the strip and headline", async () => {
    const getSum = jest
      .fn()
      // First read: both days logged and on target.
      .mockResolvedValueOnce([
        makeSummary(YESTERDAY, 2000, 2000),
        makeSummary(TODAY, 2000, 2000),
      ])
      // After the delete on Today: today's only item was voided, so the day
      // reads back unlogged (has_intake false, zeroed intake).
      .mockResolvedValueOnce([
        makeSummary(YESTERDAY, 2000, 2000),
        makeSummary(TODAY, 0, 2000, false),
      ]);
    const listWeights = jest.fn().mockResolvedValue([]);
    const harness = mountHarness({
      getDailySummaryRange: getSum,
      listWeightEntries: listWeights,
    });
    trees.push(harness.tree);
    await act(async () => {});

    expect(getSum).toHaveBeenCalledTimes(1);
    expect(textContent(harness.tree)).toContain("2/2 days on target");
    expect(cellLabel(harness.tree, TODAY)).toBe("Today: on target");

    // Switch to Today (blur) — no fetch — then back to Trends (focus gain).
    harness.blur();
    expect(getSum).toHaveBeenCalledTimes(1);
    harness.focus();
    await act(async () => {});

    expect(getSum).toHaveBeenCalledTimes(2);
    const content = textContent(harness.tree);
    expect(content).toContain("1/1 days on target");
    expect(content).not.toContain("2/2 days on target");
    // The affected day's strip cell reflects the deletion too.
    expect(cellLabel(harness.tree, TODAY)).toBe("Today: no data");
    // The weight read shares the same focus-refresh trigger.
    expect(listWeights).toHaveBeenCalledTimes(2);
  });

  it("derives the date window from the time of focus, not first mount", async () => {
    const getSum = jest.fn().mockResolvedValue([]);
    const harness = mountHarness({ getDailySummaryRange: getSum });
    trees.push(harness.tree);
    await act(async () => {});

    const mountBounds = rangeBounds("1M", NOW);
    expect(getSum).toHaveBeenCalledTimes(1);
    expect(getSum.mock.calls[0].slice(1)).toEqual([
      mountBounds.from,
      mountBounds.to,
    ]);

    // The app stays open across midnight; on the next focus the window must
    // roll to the new day.
    const nextDay = new Date(NOW.getTime() + 24 * 60 * 60 * 1000);
    harness.setClock(nextDay);
    harness.blur();
    harness.focus();
    await act(async () => {});

    const rolledBounds = rangeBounds("1M", nextDay);
    expect(rolledBounds.to).not.toEqual(mountBounds.to);
    expect(getSum).toHaveBeenCalledTimes(2);
    expect(getSum.mock.calls[1].slice(1)).toEqual([
      rolledBounds.from,
      rolledBounds.to,
    ]);
  });

  it("does not refetch on re-renders while the screen stays focused (no loop)", async () => {
    const getSum = jest.fn().mockResolvedValue([]);
    const harness = mountHarness({ getDailySummaryRange: getSum });
    trees.push(harness.tree);
    await act(async () => {});
    expect(getSum).toHaveBeenCalledTimes(1);

    harness.blur();
    harness.focus();
    await act(async () => {});
    expect(getSum).toHaveBeenCalledTimes(2);

    // Renders while focused — including the one the refresh itself caused —
    // must not schedule further reads.
    harness.rerender();
    harness.rerender();
    harness.rerender();
    await act(async () => {});
    expect(getSum).toHaveBeenCalledTimes(2);
  });

  it("refreshes in place: settled content stays visible while the focus read is in flight", async () => {
    let resolveSecond!: (v: DailySummaryDTO[]) => void;
    const getSum = jest
      .fn()
      .mockResolvedValueOnce([makeSummary(TODAY, 2000, 2000)])
      .mockReturnValueOnce(
        new Promise<DailySummaryDTO[]>((r) => {
          resolveSecond = r;
        }),
      );
    const harness = mountHarness({ getDailySummaryRange: getSum });
    trees.push(harness.tree);
    await act(async () => {});
    expect(textContent(harness.tree)).toContain("Avg 2000 kcal/day");
    expect(skeletonCount(harness.tree)).toBe(0);

    harness.blur();
    harness.focus();
    await act(async () => {});

    // In flight: the previous strip/headline are still on screen — never an
    // unmount-to-skeleton swap (calm-by-default).
    expect(getSum).toHaveBeenCalledTimes(2);
    expect(skeletonCount(harness.tree)).toBe(0);
    expect(textContent(harness.tree)).toContain("Avg 2000 kcal/day");

    // Fresh data replaces the content in place.
    await act(async () => {
      resolveSecond([makeSummary(TODAY, 1500, 2000)]);
    });
    expect(skeletonCount(harness.tree)).toBe(0);
    expect(textContent(harness.tree)).toContain("Avg 1500 kcal/day");
  });
});
