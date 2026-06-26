/**
 * Local mock state for the Today shell.
 *
 * This shape is an INTERNAL PLACEHOLDER, not a committed contract. The real
 * timeline DTOs arrive with the logging-spine stories; nothing here should be
 * imported by the backend or treated as a wire format. It exists only so the
 * Today screen has realistic, fully offline data to render (see FTY-013).
 *
 * Per the system overview, entries appear immediately as `pending` and update
 * to `complete` once estimation resolves. We model that split here without any
 * networking so the UI can be built and tested deterministically.
 */

export type EntryStatus = "pending" | "complete";

export type EntryKind = "food" | "exercise";

export interface TodayEntry {
  /** Stable identifier for list keys; opaque to the UI. */
  readonly id: string;
  /** Whether this entry adds (food) or subtracts (exercise) calories. */
  readonly kind: EntryKind;
  /** The user's natural-language input, echoed back into the timeline. */
  readonly text: string;
  /** `pending` until estimation resolves, then `complete`. */
  readonly status: EntryStatus;
  /**
   * Estimated calories: positive for food consumed, positive magnitude for
   * exercise burned. `null` while the entry is still `pending`.
   */
  readonly calories: number | null;
  /**
   * Whether a completed estimate is backed by a retrieved source rather than a
   * model prior alone. Surfaced as an evidence indicator. `null` while pending.
   */
  readonly sourceBacked: boolean | null;
}

export interface DaySummary {
  readonly pendingCount: number;
  readonly completeCount: number;
  /** Calories from completed food entries. */
  readonly consumed: number;
  /** Calories from completed exercise entries. */
  readonly burned: number;
  /** consumed - burned, over completed entries only. */
  readonly net: number;
}

/** Synthetic Today timeline. No real user data; safe to commit. */
export const MOCK_TODAY_ENTRIES: readonly TodayEntry[] = [
  {
    id: "e1",
    kind: "food",
    text: "Greek yogurt with blueberries and honey",
    status: "complete",
    calories: 220,
    sourceBacked: true,
  },
  {
    id: "e2",
    kind: "exercise",
    text: "30 minute brisk walk",
    status: "complete",
    calories: 140,
    sourceBacked: true,
  },
  {
    id: "e3",
    kind: "food",
    text: "Chicken burrito bowl, no rice",
    status: "complete",
    calories: 540,
    sourceBacked: false,
  },
  {
    id: "e4",
    kind: "food",
    text: "Cold brew with a splash of oat milk",
    status: "pending",
    calories: null,
    sourceBacked: null,
  },
];

/** Entries still awaiting an estimate, in input order. */
export function selectPending(
  entries: readonly TodayEntry[],
): readonly TodayEntry[] {
  return entries.filter((entry) => entry.status === "pending");
}

/** Entries with a resolved estimate, in input order. */
export function selectComplete(
  entries: readonly TodayEntry[],
): readonly TodayEntry[] {
  return entries.filter((entry) => entry.status === "complete");
}

/**
 * Roll up the day's completed entries. Pending entries contribute no calories
 * because their estimate has not resolved yet.
 */
export function summarizeDay(entries: readonly TodayEntry[]): DaySummary {
  let consumed = 0;
  let burned = 0;
  let completeCount = 0;
  let pendingCount = 0;

  for (const entry of entries) {
    if (entry.status === "pending") {
      pendingCount += 1;
      continue;
    }
    completeCount += 1;
    const calories = entry.calories ?? 0;
    if (entry.kind === "food") {
      consumed += calories;
    } else {
      burned += calories;
    }
  }

  return {
    pendingCount,
    completeCount,
    consumed,
    burned,
    net: consumed - burned,
  };
}

/**
 * Accessibility label describing an entry's estimation status and, when
 * complete, whether its estimate is source-backed. Keeps the visual status
 * glyphs paired with screen-reader text.
 */
export function statusAccessibilityLabel(entry: TodayEntry): string {
  if (entry.status === "pending") {
    return "Estimating";
  }
  return entry.sourceBacked ? "Estimated from a source" : "Estimated";
}
