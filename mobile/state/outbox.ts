/**
 * The offline logging outbox — pure model and drain algorithm (FTY-104).
 *
 * When the device cannot reach the Fatty server, a raw log entry is captured
 * into a durable on-device outbox instead of being dropped. Each queued item
 * carries a stable, client-generated idempotency key (created once at capture
 * time, never regenerated). On reconnect the outbox drains by submitting each
 * entry through FTY-096's idempotent create endpoint with that key, so a retry
 * after an ambiguous network failure — where the server may already have
 * accepted the submit — converges to a single event and never double-counts.
 *
 * This module is deliberately free of React and platform storage: the queue's
 * persistence is an injectable {@link OutboxStore} (see `outboxStore.ts` for the
 * expo-file-system implementation) and the network is an injectable
 * {@link OutboxSubmit}. That keeps the dedup-critical drain logic unit-testable
 * with plain in-memory fakes.
 *
 * Privacy: a queued entry's `rawText` is sensitive personal data. It lives only
 * in the injected store (on-device, scoped to the signed-in user) and is never
 * logged here.
 */

import type { LogEventDTO } from "@/api/logEvents";
import { isRetryableError, isUnreachableError } from "@/state/reachability";

/**
 * Local sync state of a queued entry: `queued` → `submitting` →
 * `accepted` (server took it; about to leave the outbox) or `failed` (the server
 * rejected it with a *terminal* client error — kept for visibility rather than
 * silently retried forever). A transient server error keeps the entry `queued`
 * for a later pass instead.
 */
export type OutboxSyncState = "queued" | "submitting" | "accepted" | "failed";

/** A single durably-stored offline capture. */
export interface OutboxEntry {
  /**
   * Stable client idempotency key (a UUID minted at capture time and never
   * regenerated). The dedup guarantee rests on this being constant across every
   * retry of the same entry.
   */
  readonly idempotencyKey: string;
  /** The signed-in user who captured this entry; the store is scoped to them. */
  readonly userId: string;
  /** The raw natural-language text, exactly as captured. Sensitive. */
  readonly rawText: string;
  /** ISO timestamp of capture (used for feed ordering). */
  readonly capturedAt: string;
  /** Where this entry is in the local sync lifecycle. */
  readonly syncState: OutboxSyncState;
}

/**
 * Durable, per-user persistence for the outbox. Implementations store entries
 * on-device scoped to `userId` so one user's queue never leaks to another.
 */
export interface OutboxStore {
  /** Load the user's queued entries (empty array when none / unreadable). */
  load(userId: string): Promise<readonly OutboxEntry[]>;
  /** Persist the user's full queue, replacing what was stored. */
  save(userId: string, entries: readonly OutboxEntry[]): Promise<void>;
  /** Remove the user's queue entirely (sign-out). */
  clear(userId: string): Promise<void>;
}

/** Submit one entry to the server; resolves with the created/replayed event. */
export type OutboxSubmit = (entry: OutboxEntry) => Promise<LogEventDTO>;

/** Build a fresh `queued` outbox entry from a just-captured input. */
export function createOutboxEntry(args: {
  readonly idempotencyKey: string;
  readonly userId: string;
  readonly rawText: string;
  readonly capturedAt: string;
}): OutboxEntry {
  return {
    idempotencyKey: args.idempotencyKey,
    userId: args.userId,
    rawText: args.rawText,
    capturedAt: args.capturedAt,
    syncState: "queued",
  };
}

/**
 * Generate an opaque idempotency key — a RFC-4122 v4 UUID. The server treats the
 * key as opaque data (per the log-events contract), so a non-cryptographic
 * source is sufficient here: the key only needs to be unique per capture on this
 * device, and a v4 UUID's collision probability is negligible.
 */
export function generateIdempotencyKey(): string {
  const hex = "0123456789abcdef";
  let out = "";
  for (let i = 0; i < 36; i++) {
    if (i === 8 || i === 13 || i === 18 || i === 23) {
      out += "-";
    } else if (i === 14) {
      out += "4";
    } else if (i === 19) {
      // Variant bits: one of 8, 9, a, b.
      out += hex[8 + Math.floor(Math.random() * 4)];
    } else {
      out += hex[Math.floor(Math.random() * 16)];
    }
  }
  return out;
}

/** A queued entry the server accepted on this drain, with its server event. */
interface AcceptedEntry {
  readonly entry: OutboxEntry;
  readonly event: LogEventDTO;
}

/** Outcome of a single drain pass. */
export interface DrainResult {
  /**
   * The queue after the pass: entries still `queued` (transient failures, or
   * skipped once the connection dropped mid-drain) and any `failed` entries.
   * Accepted entries are removed — they hand off to the normal server-driven
   * pending → resolved flow via {@link DrainResult.accepted}.
   */
  readonly entries: readonly OutboxEntry[];
  /** Entries the server accepted this pass (fresh create or idempotent replay). */
  readonly accepted: readonly AcceptedEntry[];
  /** Whether the server answered at all this pass (true ⇒ we are reachable). */
  readonly reachedServer: boolean;
}

/**
 * Coerce a loaded queue into a clean starting state: a `submitting` entry left
 * over from a process that died mid-drain is reset to `queued` so it is retried,
 * and any stale `accepted` entry is dropped (it had already left the queue).
 */
export function normalizeLoaded(
  entries: readonly OutboxEntry[],
): readonly OutboxEntry[] {
  return entries
    .filter((e) => e.syncState !== "accepted")
    .map((e) => (e.syncState === "submitting" ? { ...e, syncState: "queued" } : e));
}

/**
 * Drain the outbox once, serially. Each `queued` entry is submitted with its own
 * idempotency key; on success it is accepted and leaves the queue. The pass is
 * resilient and dedup-safe:
 *
 * - **Success** → the entry is accepted (a fresh `201` or an idempotent `200`
 *   replay are indistinguishable here — both mean "the server has it").
 * - **Unreachable** (network failure) → the entry stays `queued`, and the drain
 *   stops immediately: the connection is gone, so hammering the rest is wasteful
 *   and they are retried on the next pass. No entry is dropped or duplicated.
 * - **Transient rejection** (the server answered `5xx`/`429`/`401`) → the entry
 *   stays `queued` and the drain stops: the server is reachable but temporarily
 *   unable to take the entry (restarting/deploying, rate-limited, or an expired
 *   session), so the rest would hit the same wall and are retried next pass.
 *   This is what keeps "resolve on reconnect" from abandoning a capture when the
 *   server is briefly unhealthy at exactly the moment a device comes back.
 * - **Terminal rejection** (the server answered a terminal client error such as
 *   `422` validation) → the entry is marked `failed`. Resubmitting it would be
 *   rejected the same way, so it is kept for visibility rather than retried
 *   forever, and the drain continues with the rest.
 *
 * `onChange` is invoked with the working queue as states advance
 * (`queued` → `submitting` → resolved) so a caller can reflect progress and
 * persist incrementally. It never receives `accepted` entries — those are
 * returned separately to hand off to the feed.
 */
export async function drainOutbox(opts: {
  readonly entries: readonly OutboxEntry[];
  readonly submit: OutboxSubmit;
  readonly onChange?: (entries: readonly OutboxEntry[]) => void;
}): Promise<DrainResult> {
  const { entries, submit, onChange } = opts;
  const working: OutboxEntry[] = entries.map((e) =>
    e.syncState === "submitting" ? { ...e, syncState: "queued" } : e,
  );
  const accepted: AcceptedEntry[] = [];
  let reachedServer = false;
  let stopDraining = false;

  const visible = () => working.filter((e) => e.syncState !== "accepted");

  for (let i = 0; i < working.length; i++) {
    const entry = working[i];
    if (entry.syncState !== "queued") continue;
    if (stopDraining) continue;

    working[i] = { ...entry, syncState: "submitting" };
    onChange?.(visible());

    try {
      const event = await submit(entry);
      reachedServer = true;
      working[i] = { ...entry, syncState: "accepted" };
      accepted.push({ entry: working[i], event });
      onChange?.(visible());
    } catch (error) {
      if (isUnreachableError(error)) {
        // Connection dropped — keep this entry and stop draining the rest.
        working[i] = { ...entry, syncState: "queued" };
        stopDraining = true;
      } else if (isRetryableError(error)) {
        // The server answered, but with a transient error (5xx/429, or a 401
        // from a session that expired mid-drain). Keep the entry queued to
        // retry on a later pass and stop draining — the rest would hit the same
        // condition. This preserves the capture instead of stranding it.
        reachedServer = true;
        working[i] = { ...entry, syncState: "queued" };
        stopDraining = true;
      } else {
        // The server rejected this entry with a terminal client error (e.g. 422
        // validation): reachable, and resubmitting would be rejected the same
        // way. Mark it failed and move on.
        reachedServer = true;
        working[i] = { ...entry, syncState: "failed" };
      }
      onChange?.(visible());
    }
  }

  return {
    entries: working.filter((e) => e.syncState !== "accepted"),
    accepted,
    reachedServer,
  };
}

/**
 * Fold a drain pass back into the live queue without losing an entry captured
 * *while the drain was in flight*.
 *
 * A drain works from a snapshot of the queue taken when it started. If the user
 * captures a new offline entry during that drain, replacing the queue with the
 * drain's result would silently drop the just-captured entry — the exact data
 * loss this feature exists to prevent. So instead of overwriting, keep every
 * entry that was *not* part of the drained snapshot (identified by its stable
 * idempotency key) and append the drain's resolved view of the snapshot.
 *
 * `snapshotKeys` are the keys the drain started from; `drained` is its current
 * view of just those entries (accepted ones already removed). Newly-captured
 * entries — present in `latest` but absent from `snapshotKeys` — are preserved.
 */
export function mergeDrainResult(
  latest: readonly OutboxEntry[],
  snapshotKeys: ReadonlySet<string>,
  drained: readonly OutboxEntry[],
): readonly OutboxEntry[] {
  const extras = latest.filter((e) => !snapshotKeys.has(e.idempotencyKey));
  return [...drained, ...extras];
}

/** Count entries the user is still waiting to send (queued or in flight). */
export function pendingCount(entries: readonly OutboxEntry[]): number {
  return entries.filter(
    (e) => e.syncState === "queued" || e.syncState === "submitting",
  ).length;
}

/** Whether any entry still needs a (re)try on the next drain pass. */
export function hasQueuedWork(entries: readonly OutboxEntry[]): boolean {
  return entries.some((e) => e.syncState === "queued");
}
