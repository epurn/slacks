/**
 * The React seam that ties the offline outbox (FTY-104) to a screen.
 *
 * It owns three things and keeps them in sync:
 *  - the in-memory view of the user's queued entries (loaded from the durable
 *    {@link OutboxStore} on sign-in, so they survive an app restart);
 *  - the {@link ReachabilityState} that drives the calm connection banner; and
 *  - the drain loop that submits queued entries on reconnect, deduped by each
 *    entry's stable idempotency key.
 *
 * Reachability is inferred from real submit outcomes (see `reachability.ts`):
 * the periodic retry while a backlog exists *is* the reconnect probe, so no
 * network-status native module is needed. A successful online capture also
 * nudges a drain immediately via {@link OfflineQueue.drainNow}.
 *
 * Sign-out (the signed-in user changing, including to `null`) clears the
 * previous user's queue from on-device storage, so a queued entry never persists
 * for or leaks to a different user of the device. This is keyed on a real user
 * transition — not on the screen unmounting — so navigating away from the Log
 * tab never wipes the durable queue.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type { LogEventDTO } from "@/api/logEvents";
import {
  drainOutbox,
  hasQueuedWork,
  normalizeLoaded,
  type OutboxEntry,
  type OutboxStore,
  type OutboxSubmit,
} from "@/state/outbox";
import { useIntervalPolling } from "@/state/polling";
import type { ReachabilityState } from "@/state/reachability";

/** Default reconnect-retry cadence: calm on battery, prompt enough to feel live. */
export const OUTBOX_RETRY_INTERVAL_MS = 8000;

/** What a screen needs from the offline queue. */
export interface OfflineQueue {
  /** Connection state for the banner. */
  readonly reachability: ReachabilityState;
  /** Entries the user is still waiting to send (queued / in flight / failed). */
  readonly entries: readonly OutboxEntry[];
  /** Durably enqueue a just-captured entry and go offline. */
  enqueue(entry: OutboxEntry): Promise<void>;
  /** Attempt a drain now (e.g. after a successful online capture). */
  drainNow(): void;
}

const EMPTY: readonly OutboxEntry[] = [];

export function useOfflineQueue(args: {
  /** The signed-in user id, or `null` when signed out. */
  readonly userId: string | null;
  /** Submit one entry to the server (wired to the create endpoint + session). */
  readonly submit: OutboxSubmit;
  /** Durable per-user persistence. */
  readonly store: OutboxStore;
  /** Called when an entry is accepted, to hand it to the normal feed flow. */
  readonly onAccepted: (entry: OutboxEntry, event: LogEventDTO) => void;
  /** Reconnect-retry cadence (injectable for tests). */
  readonly retryIntervalMs?: number;
}): OfflineQueue {
  const {
    userId,
    submit,
    store,
    onAccepted,
    retryIntervalMs = OUTBOX_RETRY_INTERVAL_MS,
  } = args;

  const [entries, setEntries] = useState<readonly OutboxEntry[]>(EMPTY);
  const [reachability, setReachability] = useState<ReachabilityState>("online");

  const mountedRef = useRef(true);
  const draining = useRef(false);
  const prevUserId = useRef<string | null>(null);
  // Latest values mirrored into refs (updated in an effect, never during render)
  // so the drain/enqueue callbacks read fresh values without re-creating.
  const entriesRef = useRef(entries);
  const submitRef = useRef(submit);
  const onAcceptedRef = useRef(onAccepted);
  useEffect(() => {
    entriesRef.current = entries;
    submitRef.current = submit;
    onAcceptedRef.current = onAccepted;
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const drain = useCallback(async () => {
    if (draining.current || !userId) return;
    const current = entriesRef.current;
    if (!hasQueuedWork(current)) return;

    draining.current = true;
    if (mountedRef.current) setReachability("reconnecting");
    try {
      const result = await drainOutbox({
        entries: current,
        submit: (entry) => submitRef.current(entry),
        onChange: (live) => {
          if (mountedRef.current) setEntries(live);
        },
      });
      // Always persist the durable outcome, even if the screen has unmounted —
      // the queue must survive. UI updates are gated on still being mounted.
      await store.save(userId, result.entries);
      if (mountedRef.current) {
        for (const { entry, event } of result.accepted) {
          onAcceptedRef.current(entry, event);
        }
        setEntries(result.entries);
        setReachability(hasQueuedWork(result.entries) ? "offline" : "online");
      }
    } finally {
      draining.current = false;
    }
  }, [userId, store]);

  // Load the queue when the signed-in user changes, and purge the *previous*
  // user's on-device queue on a real user transition (sign-out / switch). Keyed
  // on the transition rather than effect-cleanup so unmount (navigation) never
  // clears the durable queue.
  useEffect(() => {
    const previous = prevUserId.current;
    if (previous !== null && previous !== userId) {
      void store.clear(previous);
    }
    prevUserId.current = userId;

    if (!userId) return;
    let active = true;
    void store.load(userId).then((loaded) => {
      if (!active || !mountedRef.current) return;
      const normalized = normalizeLoaded(loaded);
      // Nothing stored ⇒ the defaults (empty / online) already hold; skip the
      // state update so a mount with no backlog causes no extra render.
      if (normalized.length === 0) return;
      setEntries(normalized);
      setReachability(hasQueuedWork(normalized) ? "offline" : "online");
    });
    return () => {
      active = false;
    };
  }, [userId, store]);

  const enqueue = useCallback(
    async (entry: OutboxEntry) => {
      if (!userId) return;
      const next = [...entriesRef.current, entry];
      if (mountedRef.current) {
        setEntries(next);
        setReachability("offline");
      }
      // Persist immediately — this is the durability guarantee (survives restart).
      await store.save(userId, next);
    },
    [userId, store],
  );

  const drainNow = useCallback(() => {
    if (!userId) return;
    if (hasQueuedWork(entriesRef.current)) {
      void drain();
    } else if (mountedRef.current) {
      // The caller just reached the server, so we are online and caught up.
      setReachability("online");
    }
  }, [userId, drain]);

  // Periodic reconnect probe: while a backlog exists, retry on a calm cadence.
  useIntervalPolling(
    Boolean(userId) && hasQueuedWork(entries),
    retryIntervalMs,
    () => void drain(),
  );

  // When signed out, present a clean empty/online surface regardless of any
  // lingering in-memory state from a prior session.
  return userId
    ? { reachability, entries, enqueue, drainNow }
    : { reachability: "online", entries: EMPTY, enqueue, drainNow };
}
