/**
 * Secure on-device persistence for the signed-in session (FTY-090).
 *
 * The session record `{ serverUrl, token, userId }` is persisted as **one
 * atomic value** (a single JSON string under a single key) in the OS
 * keychain/keystore via `expo-secure-store`. The bearer token is a credential
 * and must never live in `AsyncStorage`, plain files, or app state alone, and
 * is never logged. The (non-secret) `serverUrl` and `userId` ride in the same
 * record on purpose: it keeps the token and the server it is valid against from
 * ever drifting apart across a torn read, and avoids a second storage key.
 *
 * A missing, unreadable, corrupt, or partial record is treated as **no
 * session** (`null`) — a half session is never hydrated.
 */

import * as SecureStore from "expo-secure-store";

import type { SessionRecord } from "@/state/session";

/** Single keychain key holding the whole session record as a JSON string. */
const SESSION_KEY = "fatty.session.v1";

/** The injectable persistence seam for the session record. */
export interface SessionStore {
  /** Persist the session record atomically. */
  save(session: SessionRecord): Promise<void>;
  /** Load the session record, or `null` when there is none / it is unusable. */
  load(): Promise<SessionRecord | null>;
  /** Remove the session record. */
  clear(): Promise<void>;
}

/** True only for a complete record with all three non-empty string fields. */
function isSessionRecord(value: unknown): value is SessionRecord {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const r = value as Record<string, unknown>;
  return (
    typeof r.serverUrl === "string" &&
    r.serverUrl !== "" &&
    typeof r.token === "string" &&
    r.token !== "" &&
    typeof r.userId === "string" &&
    r.userId !== ""
  );
}

/** The on-device secure session store. */
export const secureSessionStore: SessionStore = {
  async save(session: SessionRecord): Promise<void> {
    await SecureStore.setItemAsync(SESSION_KEY, JSON.stringify(session));
  },

  async load(): Promise<SessionRecord | null> {
    let raw: string | null;
    try {
      raw = await SecureStore.getItemAsync(SESSION_KEY);
    } catch {
      // Keychain read failure → fail closed to no session.
      return null;
    }
    if (raw === null) {
      return null;
    }
    try {
      const parsed: unknown = JSON.parse(raw);
      if (!isSessionRecord(parsed)) {
        return null;
      }
      // Reconstruct explicitly so any extra stored keys are dropped.
      return {
        serverUrl: parsed.serverUrl,
        token: parsed.token,
        userId: parsed.userId,
      };
    } catch {
      // Corrupt JSON → no session, never a half-hydrated one.
      return null;
    }
  },

  async clear(): Promise<void> {
    await SecureStore.deleteItemAsync(SESSION_KEY);
  },
};
