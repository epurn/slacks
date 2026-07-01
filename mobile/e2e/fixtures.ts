/**
 * Synthetic E2E fixtures (FTY-160).
 *
 * All data is fabricated for testing only — no real tokens, user logs, or body
 * data. These constants live in the public repo and must never carry secrets,
 * machine paths, or private data.
 */

import type { SessionRecord } from '@/state/session';
import type { ProfileDTO } from '@/api/profile';
import type { DailySummaryDTO, TargetReadModel } from '@/api/dailySummary';

export const E2E_SERVER_URL = 'http://localhost:8000';

/**
 * Synthetic session — NOT a real credential. The token is an obviously fake
 * string that can never authenticate against a real backend; it is only
 * accepted by the in-process E2E mock fetch installed in launchMode.ts.
 */
export const E2E_SESSION: SessionRecord = {
  serverUrl: E2E_SERVER_URL,
  token: 'e2e-synthetic-token-not-a-real-credential',
  userId: 'e2e-user-00000000-0000-0000-0000-000000000000',
};

/**
 * Complete profile fixture — passes isProfileComplete() in state/onboarding.ts
 * so the onboarding gate routes to Today rather than the onboarding wizard.
 */
export const E2E_PROFILE: ProfileDTO = {
  user_id: E2E_SESSION.userId,
  height_m: 1.75,
  weight_kg: 75,
  birth_year: 1990,
  metabolic_formula: 'mifflin_st_jeor_plus5',
  units_preference: 'metric',
  timezone: 'America/Chicago',
  updated_at: '2025-01-01T00:00:00Z',
};

/** Minimal valid target fixture for the goals/target endpoint. */
export const E2E_TARGET: TargetReadModel = {
  calories: { effective: 2000, derived: 2000, source: 'derived' },
  protein_g: { effective: 150, derived: 150, source: 'derived' },
  carbs_g: { effective: 200, derived: 200, source: 'derived' },
  fat_g: { effective: 65, derived: 65, source: 'derived' },
};

/** Zero daily summary for an empty E2E day. */
export const E2E_DAILY_SUMMARY: DailySummaryDTO = {
  date: '2026-01-01',
  intake: { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 },
  has_intake: false,
  target: E2E_TARGET,
  exercise: { active_calories: 0 },
};

/**
 * URL patterns the E2E mock fetch responds to. Keyed by the path suffix after
 * the user-scoped base, so the mock works for any userId/server combination.
 *
 * The suffixes MUST match the segments the real API clients pass to
 * `userScopedUrl` (see `api/*.ts`): `getTarget` requests `/target` (not
 * `/goals/target`) and `listTodayLogEvents` requests `/log-events` (not
 * `/log-events/today`). The mock strips the query string before matching, so
 * the optional `?day=` on those calls is handled. `launchMode.test.ts` drives
 * the real clients through this map to catch any future drift.
 */
export const E2E_FIXTURE_MAP: Record<string, unknown> = {
  '/profile': E2E_PROFILE,
  '/target': E2E_TARGET,
  '/log-events': [],
  '/daily-summary': E2E_DAILY_SUMMARY,
};
