/**
 * Durable, per-user on-device persistence for the offline outbox (FTY-104),
 * backed by the Expo SDK 56 File/Paths API (the same approach as
 * `cadenceAdapter.ts`).
 *
 * Each signed-in user gets their own file in the document directory (safe from
 * system eviction, unlike the cache directory). Scoping the file by user id is
 * what keeps one user's queued raw text from ever leaking to another user of the
 * device, and what lets sign-out delete exactly that user's queue.
 *
 * Privacy: the file holds `raw_text`, which is sensitive personal data. It is
 * stored on-device only, never logged, and never transmitted anywhere except the
 * authenticated FTY-096 create endpoint when the entry drains. Read/parse
 * failures fail closed to an empty queue rather than throwing.
 */

import { File, Paths } from "expo-file-system";

import type { OutboxEntry, OutboxStore } from "@/state/outbox";

/**
 * Per-user file name. The user id is a server-issued UUID, but it is sanitised
 * defensively (only `[A-Za-z0-9_-]`) so it can never escape the document
 * directory or collide across users.
 */
function outboxFileName(userId: string): string {
  const safe = userId.replace(/[^A-Za-z0-9_-]/g, "_");
  return `fatty-outbox-${safe}.json`;
}

function outboxFile(userId: string): File {
  return new File(Paths.document, outboxFileName(userId));
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
  async load(userId: string): Promise<readonly OutboxEntry[]> {
    try {
      const file = outboxFile(userId);
      if (!file.exists) return [];
      const raw = await file.text();
      const parsed: unknown = JSON.parse(raw);
      if (!Array.isArray(parsed)) return [];
      // Keep only well-formed entries owned by this user (defence in depth).
      return parsed.filter(
        (e): e is OutboxEntry => isOutboxEntry(e) && e.userId === userId,
      );
    } catch {
      // Corrupt/unreadable store fails closed to an empty queue.
      return [];
    }
  },

  async save(userId: string, entries: readonly OutboxEntry[]): Promise<void> {
    const file = outboxFile(userId);
    if (entries.length === 0) {
      // Nothing to keep — remove the file rather than leaving an empty array on
      // disk, so a drained/cleared queue leaves no sensitive-data residue.
      if (file.exists) file.delete();
      return;
    }
    file.write(JSON.stringify(entries));
  },

  async clear(userId: string): Promise<void> {
    const file = outboxFile(userId);
    if (file.exists) file.delete();
  },
};
