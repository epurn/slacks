/**
 * Reachability state and the calm connection banner (FTY-104).
 *
 * Offline-queue logging needs to know one thing: can we reach the Fatty server
 * right now? Rather than depend on a separate network-status native module, this
 * is inferred from the outcome of the real create/submit attempts the queue
 * already makes — a network-layer failure means unreachable, while any HTTP
 * answer (even a rejection) means the server was reached. The periodic drain
 * doubles as the reconnect probe: there is nothing to detect when the queue is
 * empty, and when it is not, every drain attempt is itself a live reachability
 * check.
 *
 * The banner copy lives here (pure, testable). It is deliberately calm: it never
 * reads as an error or alarm, and it never uses colour as the only signal — the
 * text always states the state in words.
 */

import { LogEventApiError } from "@/api/logEvents";

/** Connection state surfaced to the user via the banner. */
export type ReachabilityState = "online" | "offline" | "reconnecting";

/**
 * Whether an error from a create/submit attempt means the server was
 * *unreachable* (a network-layer failure) rather than reached-but-rejected.
 *
 * A `LogEventApiError` carries an HTTP status, so the server answered — it was
 * reachable, and the entry should surface its error rather than be queued.
 * Anything else (fetch rejecting with a `TypeError`, e.g. "Network request
 * failed" on a device in airplane mode) means we never reached the server, so
 * the capture falls back to the offline outbox.
 */
export function isUnreachableError(error: unknown): boolean {
  return !(error instanceof LogEventApiError);
}

/** How the connection banner should render for a given state + backlog. */
export interface BannerPresentation {
  /** Whether the banner is shown at all (hidden when online and caught up). */
  readonly visible: boolean;
  /** Visible text — also used verbatim as the accessibility label. */
  readonly label: string;
  /**
   * Tone token name read from the palette. Never `coral`/error — offline is a
   * calm, expected state, not a failure.
   */
  readonly tone: "muted" | "accent";
}

function queuedSuffix(queuedCount: number): string {
  if (queuedCount <= 0) return "";
  const noun = queuedCount === 1 ? "entry" : "entries";
  return ` · ${queuedCount} ${noun} queued`;
}

/**
 * Map a reachability state + queued count to the banner presentation. Pure so
 * the copy and visibility rules are unit-tested without rendering.
 *
 * - `online` with an empty queue → hidden (calm by default; no "you're online"
 *   chrome to clutter the screen).
 * - `online` with a backlog → a brief "sending" reassurance while it drains.
 * - `offline` → a gentle note that capture still works and will send later.
 * - `reconnecting` → a quiet in-progress note while the drain runs.
 */
export function connectionBannerPresentation(
  state: ReachabilityState,
  queuedCount: number,
): BannerPresentation {
  switch (state) {
    case "offline":
      return {
        visible: true,
        tone: "muted",
        label: `Offline — you can keep logging; entries send when you're back${queuedSuffix(
          queuedCount,
        )}`,
      };
    case "reconnecting":
      return {
        visible: true,
        tone: "accent",
        label: `Reconnecting${queuedSuffix(queuedCount)}`,
      };
    case "online":
      return queuedCount > 0
        ? {
            visible: true,
            tone: "accent",
            label: `Sending${queuedSuffix(queuedCount)}`,
          }
        : { visible: false, tone: "muted", label: "" };
  }
}
