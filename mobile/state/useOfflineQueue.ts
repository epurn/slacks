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
 * Retention (FTY-277): sign-out — the owner changing, including to `null` — no
 * longer *deletes* the previous owner's durable queue. It **hides** it: the
 * in-memory view is cleared and the signed-out surface reads empty/online, but
 * the durable file survives so the *same* owner recovers its backlog on the next
 * sign-in. "Owner" is the server URL **and** the user id, so a self-hosted server
 * never shares a queue with another; the previous owner's entries are never
 * exposed while signed out and never drained under a different owner. This is
 * keyed on a real owner transition — not on the screen unmounting — so navigating
 * away from the Log tab never touches the durable queue.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { LogEventDTO } from "@/api/logEvents";
import {
  drainOutbox,
  hasQueuedWork,
  mergeDrainResult,
  normalizeLoaded,
  outboxOwnerKey,
  type OutboxEntry,
  type OutboxOwner,
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
  /**
   * The signed-in queue owner (server URL + user id), or `null` when signed out.
   * The queue is server+user scoped, so the same `userId` on two servers is two
   * distinct owners with separate durable queues.
   */
  readonly owner: OutboxOwner | null;
  /** Submit one entry to the server (wired to the create endpoint + session). */
  readonly submit: OutboxSubmit;
  /** Durable owner-scoped persistence. */
  readonly store: OutboxStore;
  /** Called when an entry is accepted, to hand it to the normal feed flow. */
  readonly onAccepted: (entry: OutboxEntry, event: LogEventDTO) => void;
  /** Reconnect-retry cadence (injectable for tests). */
  readonly retryIntervalMs?: number;
}): OfflineQueue {
  const {
    owner: ownerInput,
    submit,
    store,
    onAccepted,
    retryIntervalMs = OUTBOX_RETRY_INTERVAL_MS,
  } = args;

  // Reduce the (possibly fresh-each-render) owner object to its primitive parts,
  // then re-derive one stable owner reference. Everything downstream keys off
  // this memoized owner so a caller passing a new `{serverUrl, userId}` literal
  // each render never churns the load effect or the drain callbacks.
  const serverUrl = ownerInput?.serverUrl ?? null;
  const ownerUserId = ownerInput?.userId ?? null;
  const owner = useMemo<OutboxOwner | null>(
    () =>
      serverUrl !== null && ownerUserId !== null
        ? { serverUrl, userId: ownerUserId }
        : null,
    [serverUrl, ownerUserId],
  );

  const [entries, setEntries] = useState<readonly OutboxEntry[]>(EMPTY);
  const [reachability, setReachability] = useState<ReachabilityState>("online");

  const mountedRef = useRef(true);
  const draining = useRef(false);
  const prevOwnerKey = useRef<string | null>(null);
  // The owner the hook is currently bound to, updated synchronously by the load
  // effect. An in-flight drain closes over the owner it *started* for and polls
  // this ref to notice a sign-out/switch that happened mid-pass — the single
  // source of truth the drain guards on so it never touches the new owner.
  const activeOwnerKey = useRef<string | null>(null);
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
    (o: OutboxOwner, snapshot?: readonly OutboxEntry[]) => {
      // Default to the live ref so the last write reflects the fully-merged
      // queue; an explicit `snapshot` is used when the durable outcome must be
      // pinned to a *specific* owner (a drain aborted by an owner change, where
      // `entriesRef` has already moved on to the new owner's queue).
      const run = saveChain.current
        .catch(() => {})
        .then(() => store.save(o, snapshot ?? entriesRef.current));
      saveChain.current = run;
      return run;
    },
    [store],
  );

  const drain = useCallback(async () => {
    if (draining.current || !owner) return;
    const current = entriesRef.current;
    if (!hasQueuedWork(current)) return;

    // The owner this drain is bound to. If it changes mid-pass (sign-out or a
    // switch), the drain must not submit the rest through the new session, nor
    // fold this owner's entries back into hook state that now belongs to the new
    // owner. `activeOwnerKey` is the live authority for the current owner.
    const drainOwner = owner;
    const drainOwnerKey = outboxOwnerKey(drainOwner);
    const ownerChanged = () => activeOwnerKey.current !== drainOwnerKey;

    // Keys the drain starts from. Anything enqueued mid-drain has a fresh key
    // outside this set and is merged back in rather than overwritten.
    const snapshotKeys = new Set(current.map((e) => e.idempotencyKey));
    draining.current = true;
    if (mountedRef.current) setReachability("reconnecting");
    try {
      const result = await drainOutbox({
        entries: current,
        submit: (entry) => submitRef.current(entry),
        shouldStop: ownerChanged,
        onChange: (live) => {
          // Once the owner has changed, hook state belongs to the new owner —
          // never merge the prior owner's drain progress back into it.
          if (ownerChanged()) return;
          commitEntries(mergeDrainResult(entriesRef.current, snapshotKeys, live));
        },
      });

      if (ownerChanged()) {
        // The owner signed out or switched while this drain was in flight.
        // Persist the drain's own outcome to *its* owner's durable file (pinned
        // explicitly — `entriesRef` now holds the new owner's queue), and leave
        // the live UI, reachability, and feed untouched: the accepted entries
        // belong to the previous owner's server, not the new session.
        await persist(drainOwner, result.entries);
        return;
      }

      const merged = mergeDrainResult(
        entriesRef.current,
        snapshotKeys,
        result.entries,
      );
      entriesRef.current = merged;
      // Always persist the durable outcome, even if the screen has unmounted —
      // the queue must survive. UI updates are gated on still being mounted.
      await persist(drainOwner);
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
  }, [owner, commitEntries, persist]);

  // Load the owner's durable backlog when the owner changes, and — on a real
  // owner transition (sign-out / switch) — *hide* the previous owner's queue.
  // Hiding is memory-only: the durable file is deliberately left intact so the
  // same owner recovers it on the next sign-in (FTY-277). Keyed on the owner
  // transition rather than effect-cleanup so unmount (navigation) never touches
  // the queue.
  useEffect(() => {
    const key = owner ? outboxOwnerKey(owner) : null;
    // Publish the new owner synchronously (before the async load resolves) so an
    // in-flight drain started for the previous owner sees the change and aborts.
    activeOwnerKey.current = key;
    const previous = prevOwnerKey.current;
    if (previous !== null && previous !== key) {
      // A different owner (or sign-out): drop the previous owner's entries from
      // memory so they are never rendered while signed out and never drained
      // under the new owner. We do NOT delete the previous owner's durable file
      // — that is the retention change this story makes. The privacy guarantee
      // is that the raw text is gone from React state and the drain loop, not
      // that it is erased from disk.
      commitEntries(EMPTY);
      setReachability("online");
    }
    prevOwnerKey.current = key;

    if (!owner) return;
    let active = true;
    void store.load(owner).then((loaded) => {
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
  }, [owner, store, commitEntries]);

  const enqueue = useCallback(
    async (entry: OutboxEntry) => {
      if (!owner) return;
      // Append against the synchronous ref so a capture made during an in-flight
      // drain is never lost — the drain merges it back rather than overwriting.
      commitEntries([...entriesRef.current, entry]);
      if (mountedRef.current) setReachability("offline");
      // Persist immediately — this is the durability guarantee (survives restart).
      await persist(owner);
    },
    [owner, commitEntries, persist],
  );

  const drainNow = useCallback(() => {
    if (!owner) return;
    if (hasQueuedWork(entriesRef.current)) {
      void drain();
    } else if (mountedRef.current) {
      // The caller just reached the server, so we are online and caught up.
      setReachability("online");
    }
  }, [owner, drain]);

  // Periodic reconnect probe: while a backlog exists, retry on a calm cadence.
  useIntervalPolling(
    Boolean(owner) && hasQueuedWork(entries),
    retryIntervalMs,
    () => void drain(),
  );

  // When signed out, present a clean empty/online surface regardless of any
  // lingering in-memory state from a prior session.
  return owner
    ? { reachability, entries, enqueue, drainNow }
    : { reachability: "online", entries: EMPTY, enqueue, drainNow };
}
