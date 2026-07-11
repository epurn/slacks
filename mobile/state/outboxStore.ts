/**
 * Durable, owner-scoped on-device persistence for the offline outbox (FTY-104,
 * re-scoped in FTY-277), backed by the Expo SDK 56 File/Paths API (the same
 * approach as `cadenceAdapter.ts`).
 *
 * Each {@link OutboxOwner} — the normalized server URL **and** the user id — gets
 * its own file in the document directory (safe from system eviction, unlike the
 * cache directory). Scoping the file by server + user is what keeps one owner's
 * queued raw text from ever leaking to another user of the device, or to the same
 * `userId` on a *different* self-hosted server.
 *
 * Retention (FTY-277): the file is **not** deleted on sign-out. It is removed
 * only when the queue drains empty (`save(owner, [])`) or by an explicit
 * `clear(owner)` purge, so a queued capture survives sign-out and is recovered
 * when the same owner signs back in.
 *
 * Privacy: the file holds `raw_text`, which is sensitive personal data. It is
 * stored on-device only, never logged, and never transmitted anywhere except the
 * authenticated FTY-096 create endpoint when the entry drains. It stores no
 * bearer token or credential. Read/parse failures fail closed to an empty queue
 * rather than throwing.
 */

import { File, Paths } from "expo-file-system";

import {
  outboxOwnerKey,
  type OutboxEntry,
  type OutboxOwner,
  type OutboxStore,
} from "@/state/outbox";

/** Distinct FNV-1a offset bases for the four passes of {@link ownerDigest}. */
const OWNER_DIGEST_SEEDS = [0x811c9dc5, 0xcbf29ce4, 0x84222325, 0x9e3779b9];

/** One 32-bit FNV-1a pass over `input` from a given offset basis. */
function fnv1a32(input: string, seed: number): number {
  let hash = seed >>> 0;
  for (let i = 0; i < input.length; i++) {
    hash ^= input.charCodeAt(i);
    hash = Math.imul(hash, 0x01000193);
  }
  return hash >>> 0;
}

/**
 * Deterministic 128-bit digest (hex) of the full owner key. It disambiguates the
 * file name so two owners whose readable portions sanitise to the same string
 * (e.g. the same `userId` on two different servers) can never share a file. A
 * single 32-bit pass is not a collision-safe server+user boundary — that whole
 * class of same-prefix owners would rest on one 32-bit value — so the digest is
 * four FNV-1a passes with distinct offset bases over per-pass-salted input,
 * making an accidental collision between distinct owners negligible.
 */
function ownerDigest(input: string): string {
  return OWNER_DIGEST_SEEDS.map((seed, pass) =>
    fnv1a32(`${input}\u0000${pass}`, seed).toString(16).padStart(8, "0"),
  ).join("");
}

/**
 * Per-owner file name: a readable, sanitised user-id prefix (only `[A-Za-z0-9_-]`,
 * so it can never escape the document directory) plus a digest of the full
 * server+user owner key. Distinct owners always map to distinct files; the same
 * owner always maps to the same file. No token or credential is encoded.
 */
function outboxFileName(owner: OutboxOwner): string {
  const readable = owner.userId.replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 40);
  return `slacks-outbox-${readable}-${ownerDigest(outboxOwnerKey(owner))}.json`;
}

function outboxFile(owner: OutboxOwner): File {
  return new File(Paths.document, outboxFileName(owner));
}

function isOutboxEntry(value: unknown): value is OutboxEntry {
  if (typeof value !== "object" || value === null) return false;
  const e = value as Record<string, unknown>;
  return (
    typeof e.idempotencyKey === "string" &&
    typeof e.userId === "string" &&
    typeof e.rawText === "string" &&
    typeof e.capturedAt === "string" &&
    (e.syncState === "queued" ||
      e.syncState === "submitting" ||
      e.syncState === "accepted" ||
      e.syncState === "failed")
  );
}

/** The on-device outbox store. */
export const fileOutboxStore: OutboxStore = {
  async load(owner: OutboxOwner): Promise<readonly OutboxEntry[]> {
    try {
      const file = outboxFile(owner);
      if (!file.exists) return [];
      const raw = await file.text();
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      // Keep only well-formed entries owned by this user (defence in depth): the
      // file is already server+user scoped, and this drops any foreign entry.
      return parsed.filter(
        (e): e is OutboxEntry => isOutboxEntry(e) && e.userId === owner.userId,
      );
    } catch {
      // Corrupt/unreadable store fails closed to an empty queue.
      return [];
    }
  },

  async save(owner: OutboxOwner, entries: readonly OutboxEntry[]): Promise<void> {
    const file = outboxFile(owner);
    if (entries.length === 0) {
      // Nothing to keep — remove the file rather than leaving an empty array on
      // disk, so a drained queue leaves no sensitive-data residue.
      if (file.exists) file.delete();
      return;
    }
    file.write(JSON.stringify(entries));
  },

  async clear(owner: OutboxOwner): Promise<void> {
    // Explicit destructive purge only — never called on a normal sign-out.
    const file = outboxFile(owner);
    if (file.exists) file.delete();
  },
};
