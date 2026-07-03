/**
 * On-device memory of the active goal's pace preset, keyed by user (FTY-190).
 *
 * A goal's pace (gentle / steady / faster) is chosen when the goal is created or
 * edited, but — unlike its direction — it is not carried on any read-model the
 * client can fetch on a cold launch: `GET /goal` (FTY-189) recovers only the
 * *direction*. Without a local memory the collapsed Settings Goal row could only
 * summarise a returning user's goal by direction (`Lose`) and never as the full
 * `Lose · Steady` the story requires.
 *
 * So the app remembers the pace it last set for each signed-in user and replays
 * it on the next cold launch, alongside the authoritative direction. It is a
 * display convenience, never authoritative: a genuinely unknown pace (e.g. a
 * goal created on another device, before this memory existed) simply leaves the
 * row summarised by its real direction rather than guessing a pace. Keyed by
 * user id so a shared device never leaks one account's pace into another's row.
 *
 * Stored as a JSON file via expo-file-system (a non-sensitive display
 * preference — no weight/target number is written). The seam is injectable so
 * the SettingsScreen tests can drive it without the platform filesystem.
 */

import { File, Paths } from 'expo-file-system';

import type { PacePreset } from '@/api/goals';

/** Persistence seam for the on-device active-goal pace, per user. */
export interface GoalPaceStore {
  /** The remembered pace for `userId`, or `null` when none is remembered. */
  getGoalPace(userId: string): Promise<PacePreset | null>;
  /** Remember (or, with `null`, forget) the active-goal pace for `userId`. */
  setGoalPace(userId: string, pace: PacePreset | null): Promise<void>;
}

interface StoredGoalPace {
  paceByUser?: Record<string, PacePreset>;
}

const VALID_PACES = new Set<string>(['gentle', 'steady', 'faster']);

function isPacePreset(v: unknown): v is PacePreset {
  return typeof v === 'string' && VALID_PACES.has(v);
}

function getPaceFile(): File {
  return new File(Paths.document, 'fatty-goal-pace.json');
}

async function readStored(): Promise<StoredGoalPace> {
  try {
    const file = getPaceFile();
    if (!file.exists) return {};
    const raw = await file.text();
    const parsed = JSON.parse(raw) as StoredGoalPace;
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

/** File-based on-device pace store backed by expo-file-system. */
export const fileGoalPaceStore: GoalPaceStore = {
  async getGoalPace(userId: string): Promise<PacePreset | null> {
    const data = await readStored();
    const v = data.paceByUser?.[userId];
    return isPacePreset(v) ? v : null;
  },

  async setGoalPace(userId: string, pace: PacePreset | null): Promise<void> {
    try {
      const data = await readStored();
      const paceByUser = { ...(data.paceByUser ?? {}) };
      if (pace === null) {
        delete paceByUser[userId];
      } else {
        paceByUser[userId] = pace;
      }
      getPaceFile().write(JSON.stringify({ ...data, paceByUser }));
    } catch {
      // Best-effort: a persistence failure just means the next cold launch
      // summarises the goal by its direction alone — never a crash, and never a
      // lost goal save (the save itself already round-tripped to the server).
    }
  },
};
