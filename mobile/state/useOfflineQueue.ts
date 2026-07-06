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
  mergeDrainResult,
  normalizeLoaded,
  type OutboxEntry,
  type OutboxStore,
  type OutboxSubmit,
} from "@/state/outbox";
import { useIntervalPolling } from "@/state/polling";
import type { ReachabilityState } from "@/state/reachability";

/** Default reconnect-retry cadence: calm on battery, prompt enough to feel live. */
const OUTBOX_RETRY_INTERVAL_MS = 8000;

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
  // `entriesRef` is the *synchronous* authority for the queue: the drain and
  // enqueue callbacks read and write it directly between awaits, so neither can
  // act on a stale snapshot. `entries` state only mirrors it for rendering.
  const entriesRef = useRef(entries);
  const submitRef = useRef(submit);
  const onAcceptedRef = useRef(onAccepted);
  useEffect(() => {
    submitRef.current = submit;
    onAcceptedRef.current = onAccepted;
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Update the queue everywhere at once: the synchronous ref (read by the
  // callbacks) and the rendered state. Keeping these in lockstep is what stops a
  // capture made during an in-flight drain from being lost to a stale snapshot.
  const commitEntries = useCallback((next: readonly OutboxEntry[]) => {
    entriesRef.current = next;
    if (mountedRef.current) setEntries(next);
  }, []);

  // Serialize on-device writes through a single chain so a drain's save and a
  // concurrent enqueue's save can't interleave and clobber each other on disk.
  // Each link persists the *current* ref, so the last write always reflects the
  // fully-merged queue (drain outcome + anything enqueued meanwhile).
  const saveChain = useRef<Promise<unknown>>(Promise.resolve());
  const persist = useCallback(
    (id: string) => {
      const run = saveChain.current
        .catch(() => {})
        .then(() => store.save(id, entriesRef.current));
      saveChain.current = run;
      return run;
    },
    [store],
  );

  const drain = useCallback(async () => {
    if (draining.current || !userId) return;
    const current = entriesRef.current;
    if (!hasQueuedWork(current)) return;

    // Keys the drain starts from. Anything enqueued mid-drain has a fresh key
    // outside this set and is merged back in rather than overwritten.
    const snapshotKeys = new Set(current.map((e) => e.idempotencyKey));
    draining.current = true;
    if (mountedRef.current) setReachability("reconnecting");
    try {
      const result = await drainOutbox({
        entries: current,
        submit: (entry) => submitRef.current(entry),
        onChange: (live) => {
          commitEntries(mergeDrainResult(entriesRef.current, snapshotKeys, live));
        },
      });
      const merged = mergeDrainResult(
        entriesRef.current,
        snapshotKeys,
        result.entries,
      );
      entriesRef.current = merged;
      // Always persist the durable outcome, even if the screen has unmounted —
      // the queue must survive. UI updates are gated on still being mounted.
      await persist(userId);
      // Read the live ref (not `merged`) for the final UI sync: a capture may
      // have landed during the await, and the ref already accounts for it.
      if (mountedRef.current) {
        for (const { entry, event } of result.accepted) {
          onAcceptedRef.current(entry, event);
        }
        setEntries(entriesRef.current);
        setReachability(hasQueuedWork(entriesRef.current) ? "offline" : "online");
      }
    } finally {
      draining.current = false;
    }
  }, [userId, commitEntries, persist]);

  // Load the queue when the signed-in user changes, and purge the *previous*
  // user's on-device queue on a real user transition (sign-out / switch). Keyed
  // on the transition rather than effect-cleanup so unmount (navigation) never
  // clears the durable queue.
  useEffect(() => {
    const previous = prevUserId.current;
    if (previous !== null && previous !== userId) {
      void store.clear(previous);
      // Reset the in-memory view on a real user transition, independent of what
      // the new user's store returns. Otherwise, if the next user has no stored
      // backlog the load below early-returns and the previous user's queued
      // entries stay in component state — leaking their raw captures into the
      // new user's session (drained under the new session). The privacy
      // guarantee this slice codifies requires clearing memory, not just disk.
      commitEntries(EMPTY);
      setReachability("online");
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
      commitEntries(normalized);
      setReachability(hasQueuedWork(normalized) ? "offline" : "online");
    });
    return () => {
      active = false;
    };
  }, [userId, store, commitEntries]);

  const enqueue = useCallback(
    async (entry: OutboxEntry) => {
      if (!userId) return;
      // Append against the synchronous ref so a capture made during an in-flight
      // drain is never lost — the drain merges it back rather than overwriting.
      commitEntries([...entriesRef.current, entry]);
      if (mountedRef.current) setReachability("offline");
      // Persist immediately — this is the durability guarantee (survives restart).
      await persist(userId);
    },
    [userId, commitEntries, persist],
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
