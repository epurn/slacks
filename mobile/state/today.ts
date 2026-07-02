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

/** A time cluster: events whose `created_at` fall within a grace window. */
export interface TimeCluster {
  /** ISO datetime of the newest (anchor) event in this cluster. */
  readonly anchorTime: string;
  /** Events in the cluster, newest first. */
  readonly events: readonly LogEventDTO[];
}

/**
 * Group newest-first events into time clusters by their `created_at` timestamp.
 * Events within `windowMs` of the cluster anchor (first/newest event) are placed
 * in the same cluster. Produces clusters in newest-first order, mirroring the
 * text-message-chain style described in the Today screen UX spec.
 *
 * Default window: 10 minutes (the spec's ~10–15-minute grace window).
 */
export function clusterByTime(
  events: readonly LogEventDTO[],
  windowMs: number = 10 * 60 * 1000,
): readonly TimeCluster[] {
  if (events.length === 0) return [];

  const sorted = sortByNewest([...events]);
  const clusters: TimeCluster[] = [];

  for (const event of sorted) {
    const eventTime = new Date(event.created_at).getTime();
    if (clusters.length > 0) {
      const last = clusters[clusters.length - 1];
      const anchorTime = new Date(last.anchorTime).getTime();
      if (anchorTime - eventTime <= windowMs) {
        clusters[clusters.length - 1] = {
          ...last,
          events: [...last.events, event],
        };
        continue;
      }
    }
    clusters.push({ anchorTime: event.created_at, events: [event] });
  }

  return clusters;
}

/**
 * Format a tz-aware ISO instant as a 12-hour wall-clock label (e.g. "11:14 AM")
 * in `timeZone` — defaulting to the device's own zone — so the timeline shows
 * the local time the user actually logged (audit finding A6).
 *
 * We deliberately do **not** use `toLocaleTimeString(..., { hour12: true })`:
 * Hermes (React Native's engine) has a documented bug where that path returns
 * the wrong meridiem on device — an 11:14 AM instant renders as "11:14 PM".
 * Instead we read the hour/minute from `formatToParts` on the reliable 24-hour
 * (`h23`) cycle and derive AM/PM ourselves, so the result is correct on device
 * and exhaustively unit-testable across the 12-hour boundary cases.
 *
 * Returns "" for an unparseable timestamp rather than throwing.
 */
export function formatWallClockTime(isoTime: string, timeZone?: string): string {
  const date = new Date(isoTime);
  if (Number.isNaN(date.getTime())) return "";

  let parts: Intl.DateTimeFormatPart[];
  try {
    parts = new Intl.DateTimeFormat("en-US", {
      hour: "numeric",
      minute: "2-digit",
      hourCycle: "h23",
      ...(timeZone ? { timeZone } : {}),
    }).formatToParts(date);
  } catch {
    // Invalid/unsupported timeZone — fail soft rather than crash the timeline.
    return "";
  }

  const hourRaw = Number(parts.find((p) => p.type === "hour")?.value);
  const minute = parts.find((p) => p.type === "minute")?.value;
  if (Number.isNaN(hourRaw) || minute === undefined) return "";

  // h23 yields 0–23; normalize the h24 "24:00" midnight variant just in case.
  const hour24 = hourRaw === 24 ? 0 : hourRaw;
  const meridiem = hour24 < 12 ? "AM" : "PM";
  const hour12 = hour24 % 12 === 0 ? 12 : hour24 % 12;
  return `${hour12}:${minute} ${meridiem}`;
}
