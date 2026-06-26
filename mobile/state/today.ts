/**
 * Presentation helpers for the Today timeline (FTY-031).
 *
 * The wire model — the `LogEventDTO` and the status vocabulary — lives in
 * `@/api/logEvents`. This module maps the FTY-030 event status state machine to
 * compact, nonjudgmental UI strings and a glyph, and provides the ordering the
 * timeline renders.
 *
 * The status mapping is exhaustive over `LogEventStatus` (a `Record` keyed by
 * every status), so a new contract status cannot be added without a matching UI
 * mapping — the coding standard requires status to use icons with accessibility
 * labels, and the timeline must cover every status the contract defines.
 *
 * Since the estimator is not wired yet, real events stay `pending`; the mapping
 * still covers the terminal and intermediate statuses so the UI never looks
 * broken once estimation lands.
 */

import type { LogEventDTO, LogEventStatus } from "@/api/logEvents";

/** How a single status is surfaced in the timeline. */
export interface StatusPresentation {
  /** Compact glyph shown in the status icon. */
  readonly glyph: string;
  /** Short status label shown beside the entry text. */
  readonly label: string;
  /** Screen-reader text paired with the glyph so both convey the same status. */
  readonly accessibilityLabel: string;
}

/**
 * The exhaustive status → presentation map. Copy is compact and nonjudgmental:
 * it describes the estimate's progress, never the user's choices.
 */
const STATUS_PRESENTATION: Record<LogEventStatus, StatusPresentation> = {
  pending: {
    glyph: "…",
    label: "Waiting",
    accessibilityLabel: "Waiting to estimate",
  },
  processing: {
    glyph: "⟳",
    label: "Estimating",
    accessibilityLabel: "Estimating",
  },
  completed: {
    glyph: "✓",
    label: "Logged",
    accessibilityLabel: "Logged",
  },
  failed: {
    glyph: "!",
    label: "Couldn't estimate",
    accessibilityLabel: "Estimate didn't finish",
  },
  needs_clarification: {
    glyph: "?",
    label: "Add a detail",
    accessibilityLabel: "Needs a quick detail",
  },
};

/** Presentation for a status. Total over the contract's status vocabulary. */
export function statusPresentation(status: LogEventStatus): StatusPresentation {
  return STATUS_PRESENTATION[status];
}

/**
 * Order events newest-first for the timeline. The API returns events
 * oldest-first; sorting by `created_at` descending puts the most recent entry
 * (including a just-added optimistic one) at the top. `Array.prototype.sort` is
 * stable, so events sharing a timestamp keep their relative order.
 */
export function sortByNewest(
  events: readonly LogEventDTO[],
): readonly LogEventDTO[] {
  return [...events].sort((a, b) => b.created_at.localeCompare(a.created_at));
}

/**
 * Prefix for optimistic placeholder ids. Server ids are UUIDs, so this prefix
 * never collides with one and lets the timeline tell an unacknowledged local
 * entry from a stored event during reconciliation.
 */
export const OPTIMISTIC_ID_PREFIX = "temp-";

/** Whether an id belongs to a locally-created, not-yet-stored optimistic event. */
export function isOptimisticId(id: string): boolean {
  return id.startsWith(OPTIMISTIC_ID_PREFIX);
}

/**
 * Merge a freshly polled (or refetched) list into the current timeline (FTY-032).
 * The server list is authoritative for every event it returns. Locally-created
 * optimistic entries the server has not acknowledged yet are preserved, so a
 * poll landing mid-create never drops a just-added row; deduping by id falls out
 * of keying off the fetched ids. The result is newest-first.
 */
export function reconcileEvents(
  current: readonly LogEventDTO[],
  fetched: readonly LogEventDTO[],
): readonly LogEventDTO[] {
  const fetchedIds = new Set(fetched.map((event) => event.id));
  const unacknowledged = current.filter(
    (event) => isOptimisticId(event.id) && !fetchedIds.has(event.id),
  );
  return sortByNewest([...fetched, ...unacknowledged]);
}

/**
 * Build an optimistic `pending` event to show immediately on submit, before the
 * create round-trip resolves. `id`/`createdAt` are supplied by the caller (kept
 * out of here so this stays pure and testable); the real event from the API
 * replaces it on success.
 */
export function optimisticLogEvent(args: {
  readonly id: string;
  readonly userId: string;
  readonly rawText: string;
  readonly createdAt: string;
}): LogEventDTO {
  return {
    id: args.id,
    user_id: args.userId,
    raw_text: args.rawText,
    status: "pending",
    created_at: args.createdAt,
    updated_at: args.createdAt,
  };
}
