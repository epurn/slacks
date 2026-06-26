/**
 * Polling logic for the Today timeline (FTY-032).
 *
 * The timeline auto-refreshes while any visible event is still working toward a
 * terminal status, so a `pending` entry moves to `completed` without a manual
 * refresh — the ADR-0002 v1 update mechanism (polling, not push/websockets).
 *
 * This module holds the two pieces that decide *whether* to poll and *drive the
 * cadence*, kept pure of navigation/app-state concerns (those live in
 * `@/state/useScreenActive`) so the stop condition and the interval are unit
 * testable:
 *
 * - `hasPendingWork` — the stop condition: poll only while a non-terminal event
 *   is visible.
 * - `useIntervalPolling` — a fixed-interval timer that runs only while active
 *   and is cleared the moment it is not, so it never loops in the background
 *   draining battery or network.
 */

import { useEffect, useRef } from "react";

import type { LogEventDTO, LogEventStatus } from "@/api/logEvents";

/**
 * Fixed poll interval, in milliseconds. A conservative default: long enough to
 * stay easy on battery and network, short enough that a finished estimate
 * surfaces promptly. Not user-configurable in v1 (a non-goal); the value is the
 * only soft detail and is intentionally a single constant.
 */
export const POLL_INTERVAL_MS = 5000;

/**
 * Statuses still advancing toward a terminal state, and therefore worth polling.
 * Mirrors the FTY-030 state machine: `completed` and `failed` are terminal, and
 * `needs_clarification` waits on a user edit (Milestone 5) rather than on the
 * server — so none of those are polled. Only `pending` and `processing` are
 * in-flight on the server side.
 */
const NON_TERMINAL_STATUSES: ReadonlySet<LogEventStatus> = new Set<
  LogEventStatus
>(["pending", "processing"]);

/** Whether a single status is still server-side in-flight (poll-worthy). */
export function isNonTerminal(status: LogEventStatus): boolean {
  return NON_TERMINAL_STATUSES.has(status);
}

/**
 * The stop condition: true while at least one visible event is non-terminal.
 * When this is false the screen has nothing to wait on and polling must stop.
 */
export function hasPendingWork(events: readonly LogEventDTO[]): boolean {
  return events.some((event) => isNonTerminal(event.status));
}

/**
 * Run `onTick` every `intervalMs` while `active` is true, and not at all when it
 * is false. The interval is created on the `active → true` edge and cleared on
 * `active → false` (and on unmount), which is the start/stop/resume behavior the
 * timeline needs: stop when no work remains, resume when a new event is created
 * or the screen refocuses.
 *
 * There is no leading tick — the caller already holds fresh data at the moment
 * it decides to start, so the first refetch is one interval later. The latest
 * `onTick` is captured in a ref so a changing callback identity updates the work
 * done without tearing down and recreating the timer (which would reset the
 * cadence and could starve the next tick).
 */
export function useIntervalPolling(
  active: boolean,
  intervalMs: number,
  onTick: () => void,
): void {
  const saved = useRef(onTick);
  useEffect(() => {
    saved.current = onTick;
  }, [onTick]);

  useEffect(() => {
    if (!active) {
      return;
    }
    const id = setInterval(() => saved.current(), intervalMs);
    return () => clearInterval(id);
  }, [active, intervalMs]);
}
