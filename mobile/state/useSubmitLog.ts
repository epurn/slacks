/**
 * The shared log-submit state machine (FTY-147).
 *
 * Today and the (now-removed) Log page had copy-pasted the same
 * create / optimistic-insert / offline-enqueue / rollback logic in their
 * `handleSubmit`, and the two copies drifted — the root cause this story exists
 * to fix. This hook is the single home of that machine, so the logging surface
 * cannot diverge again.
 *
 * What it owns:
 *  - the composer text, the in-flight `submitting` flag, and the submit error;
 *  - the offline outbox seam ({@link useOfflineQueue}) + the reachability state
 *    that drives the connection banner; and
 *  - `handleSubmit`, which on a tap:
 *     1. mints a stable idempotency key (once, reused on every retry) and an
 *        optimistic placeholder id, clears the composer, and asks the screen to
 *        insert the optimistic row immediately (unmistakable acknowledgement);
 *     2. **online success** → reconciles the optimistic row to the server event,
 *        fires the resolved haptic, and drains any offline backlog;
 *     3. **server error** (the server answered) → rolls the optimistic row back
 *        and restores the composer text so retry is one tap;
 *     4. **unreachable** (network failure) → discards the optimistic row and
 *        enqueues the raw capture into the durable outbox with the same key, with
 *        no rollback-to-input — the capture is kept, never lost.
 *
 * Screen-specific optimistic work (Today's synthetic saved-food item, FTY-053)
 * lives behind the {@link SubmitLogBridge} callbacks the hook calls into, so the
 * machine stays screen-agnostic.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  LogEventApiError,
  createLogEvent as createLogEventApi,
  type LogEventDTO,
} from "@/api/logEvents";
import {
  createOutboxEntry,
  generateIdempotencyKey,
  pendingCount,
  type OutboxEntry,
  type OutboxStore,
  type OutboxSubmit,
} from "@/state/outbox";
import { fileOutboxStore } from "@/state/outboxStore";
import {
  isUnreachableError,
  type ReachabilityState,
} from "@/state/reachability";
import type { ApiSession } from "@/state/session";
import { OPTIMISTIC_ID_PREFIX, optimisticLogEvent } from "@/state/today";
import { useOfflineQueue } from "@/state/useOfflineQueue";
import { lightHaptic } from "@/utils/haptics";

const FALLBACK_SAVE_ERROR = "We couldn't save that entry. Please try again.";

/** Map a save failure to a plain, nonjudgmental message (never echoes input). */
function messageFor(error: unknown): string {
  if (error instanceof LogEventApiError) {
    return error.message;
  }
  return FALLBACK_SAVE_ERROR;
}

/**
 * The screen's optimistic-timeline operations the submit machine calls into.
 * Today implements these against its `events`/`itemsByEvent` state (and its
 * saved-food synthetic item); the hook never touches timeline state directly.
 */
export interface SubmitLogBridge {
  /**
   * Insert the optimistic pending row for a just-captured submit, before the
   * create round-trip. The screen also performs any screen-specific optimistic
   * work here (Today adds the synthetic saved-food item).
   */
  insertOptimistic(optimistic: LogEventDTO): void;
  /** Replace the optimistic row (by id) with the server's stored event. */
  reconcileOptimistic(optimisticId: string, server: LogEventDTO): void;
  /**
   * Remove the optimistic row on a server error. The hook restores the composer
   * text; the screen restores any screen-specific capture (the saved-food
   * association) so retry is one tap.
   */
  rollbackOptimistic(optimisticId: string): void;
  /**
   * Remove the optimistic row when the server was unreachable. The capture is
   * preserved in the offline outbox and re-renders as a dedicated offline row,
   * so the composer is *not* restored — the capture is kept, not lost.
   */
  discardOptimistic(optimisticId: string): void;
  /**
   * Fold a queued offline entry's server event into the timeline once it drains
   * and is accepted, so it joins the normal pending → resolved flow and counts.
   */
  acceptDrained(idempotencyKey: string, server: LogEventDTO): void;
}

/** What a screen gets from the submit machine. */
export interface UseSubmitLog {
  /** Composer text (controlled). */
  readonly text: string;
  setText(next: string): void;
  /** True while a composer submit is in flight. */
  readonly submitting: boolean;
  setSubmitting(next: boolean): void;
  /** Submit error to surface beside the composer (null when none). */
  readonly submitError: string | null;
  setSubmitError(next: string | null): void;
  /** Submit the current composer text. */
  handleSubmit(): Promise<void>;
  /** Connection state for the banner. */
  readonly reachability: ReachabilityState;
  /** Offline-queued entries still waiting to send (for the offline rows). */
  readonly offlineEntries: readonly OutboxEntry[];
  /** How many captures are still queued (for the banner copy). */
  readonly queuedCount: number;
}

export function useSubmitLog({
  session,
  bridge,
  create = createLogEventApi,
  outboxStore = fileOutboxStore,
  retryIntervalMs,
  generateKey = generateIdempotencyKey,
  now = () => new Date().toISOString(),
}: {
  /** The authenticated session, or null when signed out. */
  session: ApiSession | null;
  /** The screen's optimistic-timeline operations. */
  bridge: SubmitLogBridge;
  /** Injectable create endpoint for tests. */
  create?: typeof createLogEventApi;
  /** Durable offline-outbox storage (FTY-104) — injectable for tests. */
  outboxStore?: OutboxStore;
  /** Reconnect-retry cadence for the outbox drain — injectable for tests. */
  retryIntervalMs?: number;
  /** Idempotency-key generator — injectable for deterministic tests. */
  generateKey?: () => string;
  /** Capture-timestamp source — injectable for deterministic tests. */
  now?: () => string;
}): UseSubmitLog {
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  // Monotonic counter for optimistic placeholder ids (the `temp-` prefix keeps
  // them recognizable to the poll reconciler so a poll landing mid-create never
  // drops the just-added row). Distinct from the idempotency key, which is the
  // durable dedup token sent to the server and carried by an offline entry.
  const optimisticSeq = useRef(0);

  // The latest bridge, read at call time so the memoized callbacks below never
  // close over a stale screen snapshot. Synced in an effect (never during
  // render) per the project's ref convention.
  const bridgeRef = useRef(bridge);
  useEffect(() => {
    bridgeRef.current = bridge;
  });

  // An offline entry accepted on a reconnect drain hands its server event to the
  // screen, which folds it into the normal server-driven pending → resolved flow.
  const handleAccepted = useCallback(
    (entry: OutboxEntry, event: LogEventDTO) => {
      bridgeRef.current.acceptDrained(entry.idempotencyKey, event);
    },
    [],
  );

  const queueSubmit = useCallback<OutboxSubmit>(
    (entry) => {
      if (!session) {
        return Promise.reject(new Error("No session for outbox submit."));
      }
      // Reuse the entry's stable idempotency key so a drain after an ambiguous
      // failure converges to a single event and never double-counts.
      return create(session, entry.rawText, entry.idempotencyKey);
    },
    [session, create],
  );

  const { reachability, entries: offlineEntries, enqueue, drainNow } =
    useOfflineQueue({
      // Owner = the bound server URL + user id, so a queue is scoped to the
      // self-hosted server it was captured against, not just the user (FTY-277).
      owner: session
        ? { serverUrl: session.baseUrl, userId: session.userId }
        : null,
      submit: queueSubmit,
      store: outboxStore,
      onAccepted: handleAccepted,
      retryIntervalMs,
    });

  const handleSubmit = useCallback(async () => {
    const trimmed = text.trim();
    if (!trimmed || !session || submitting) {
      return;
    }

    // The idempotency key is minted once, here, and reused on every retry — that
    // is what makes a reconnect drain of this entry dedup-safe (FTY-104).
    const idempotencyKey = generateKey();
    const capturedAt = now();
    const optimisticId = `${OPTIMISTIC_ID_PREFIX}${optimisticSeq.current++}`;
    const optimistic = optimisticLogEvent({
      id: optimisticId,
      userId: session.userId,
      rawText: trimmed,
      createdAt: capturedAt,
    });

    // Immediate acknowledgement: the row appears and the composer clears before
    // the round-trip, so a submit never feels like a no-op.
    bridgeRef.current.insertOptimistic(optimistic);
    setText("");
    setSubmitting(true);
    setSubmitError(null);

    try {
      const created = await create(session, trimmed, idempotencyKey);
      bridgeRef.current.reconcileOptimistic(optimisticId, created);
      // Signature "entry added" beat, fired only once the server confirms — a
      // rolled-back submit never produces a misleading success haptic.
      lightHaptic();
      // We just reached the server — flush any earlier offline backlog now.
      drainNow();
    } catch (error) {
      if (isUnreachableError(error)) {
        // Unreachable: never a dead-end. Drop the transient optimistic row and
        // enqueue the raw capture; it re-renders as a calm offline row.
        bridgeRef.current.discardOptimistic(optimisticId);
        await enqueue(
          createOutboxEntry({
            idempotencyKey,
            userId: session.userId,
            rawText: trimmed,
            capturedAt,
          }),
        );
      } else {
        // The server answered with an error — surface it and restore the
        // composer (the screen restores any saved-food association) for retry.
        bridgeRef.current.rollbackOptimistic(optimisticId);
        setText(trimmed);
        setSubmitError(messageFor(error));
      }
    } finally {
      setSubmitting(false);
    }
  }, [text, session, submitting, create, generateKey, now, enqueue, drainNow]);

  return {
    text,
    setText,
    submitting,
    setSubmitting,
    submitError,
    setSubmitError,
    handleSubmit,
    reachability,
    offlineEntries,
    queuedCount: pendingCount(offlineEntries),
  };
}
