/**
 * On-device persistence for the last-known goal direction (FTY-189).
 *
 * There is no `GET /goal` read endpoint and no `direction` field on the
 * daily-summary / target read-models (see state/goalDirection.tsx), so the only
 * place the app ever learns a goal's direction is the `POST /goal` response in
 * Settings/Onboarding. Without persistence that knowledge evaporates when the
 * process dies: a returning user who cold-launches (session hydrated from the
 * keychain, never a fresh goal save) would have Trends fall back to its `loss`
 * default and mis-color a legitimate gain/maintain trend as "away".
 *
 * This store keeps the last direction the user chose so Trends can seed its
 * goal-aware delta on launch. The record is keyed with the `userId` it belongs
 * to and stored under a single key; the reader rejects a record whose `userId`
 * doesn't match the signed-in user, so a different account never inherits a
 * stale direction (and setting a new goal simply overwrites the one key).
 *
 * Direction (`loss | gain | maintain`) is a low-sensitivity preference, but we
 * reuse `expo-secure-store` — already a dependency (state/sessionStore.ts) — to
 * avoid adding a second storage backend. A missing, unreadable, corrupt, or
 * cross-account record is treated as **unknown** (`null`).
 */

import * as SecureStore from "expo-secure-store";

import type { GoalDirection } from "@/api/goals";

/** Single key holding the whole goal-direction record as a JSON string. */
const GOAL_DIRECTION_KEY = "fatty.goalDirection.v1";

/** The persisted record: the direction plus the user it belongs to. */
export interface GoalDirectionRecord {
  readonly userId: string;
  readonly direction: GoalDirection;
}

/** The injectable persistence seam for the last-known goal direction. */
export interface GoalDirectionStore {
  /** Persist the direction for `userId`, replacing any prior record. */
  save(userId: string, direction: GoalDirection): Promise<void>;
  /** Load the record, or `null` when there is none / it is unusable. */
  load(): Promise<GoalDirectionRecord | null>;
  /** Remove the record. */
  clear(): Promise<void>;
}

const DIRECTIONS: readonly GoalDirection[] = ["loss", "gain", "maintain"];

/** True only for a complete record with a non-empty userId and valid direction. */
function isGoalDirectionRecord(value: unknown): value is GoalDirectionRecord {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const r = value as Record<string, unknown>;
  return (
    typeof r.userId === "string" &&
    r.userId !== "" &&
    typeof r.direction === "string" &&
    DIRECTIONS.includes(r.direction as GoalDirection)
  );
}

/** The on-device goal-direction store. */
export const secureGoalDirectionStore: GoalDirectionStore = {
  async save(userId: string, direction: GoalDirection): Promise<void> {
    await SecureStore.setItemAsync(
      GOAL_DIRECTION_KEY,
      JSON.stringify({ userId, direction }),
    );
  },

  async load(): Promise<GoalDirectionRecord | null> {
    let raw: string | null;
    try {
      raw = await SecureStore.getItemAsync(GOAL_DIRECTION_KEY);
    } catch {
      // Keychain read failure → treat as unknown.
      return null;
    }
    if (raw === null) {
      return null;
    }
    try {
      const parsed: unknown = JSON.parse(raw);
      if (!isGoalDirectionRecord(parsed)) {
        return null;
      }
      // Reconstruct explicitly so any extra stored keys are dropped.
      return { userId: parsed.userId, direction: parsed.direction };
    } catch {
      // Corrupt JSON → unknown, never a half-hydrated record.
      return null;
    }
  },

  async clear(): Promise<void> {
    await SecureStore.deleteItemAsync(GOAL_DIRECTION_KEY);
  },
};
