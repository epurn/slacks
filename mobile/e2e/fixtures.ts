/**
 * Synthetic E2E fixtures (FTY-160, FTY-162).
 *
 * All data is fabricated for testing only — no real tokens, user logs, or body
 * data. These constants live in the public repo and must never carry secrets,
 * machine paths, or private data.
 */

import type { SessionRecord } from '@/state/session';
import type { ProfileDTO } from '@/api/profile';
import type { DailySummaryDTO, TargetReadModel } from '@/api/dailySummary';
import type { LogEventDTO, ClarificationDTO } from '@/api/logEvents';

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
 * Static URL patterns for endpoints that never change across E2E flow phases.
 * Keyed by path suffix; the mock strips the query string before matching, so
 * the optional `?day=` on log-events/daily-summary calls is handled.
 * `launchMode.test.ts` drives the real clients through the mock to catch drift.
 *
 * Dynamic endpoints (/log-events POST+GET, /daily-summary, /clarification) are
 * handled explicitly in the stateful `createE2EMockFetch` in launchMode.ts.
 */
export const E2E_FIXTURE_MAP: Record<string, unknown> = {
  '/profile': E2E_PROFILE,
  '/target': E2E_TARGET,
};

// ─── FTY-162 clarify-flow fixtures ────────────────────────────────────────────

/** Stable id for the synthetic needs_clarification event in clarify.yaml. */
export const E2E_CLARIFY_EVENT_ID =
  'e2e-clarify-event-00000000-0000-0000-0000-000000000000';

/**
 * The seeded clarification question text. clarify.yaml asserts this exact
 * string is visible in the ClarifyMode sheet — if the sheet opens data-starved
 * (no question seeded), the generic fallback appears instead and the Maestro
 * assertion fails, proving the harness catches the FTY-149 bug class.
 */
export const E2E_CLARIFY_QUESTION =
  'What size was the coffee — small, medium, or large?';

/** Synthetic needs_clarification event for the FTY-162 clarify flow. */
export const E2E_CLARIFY_EVENT: LogEventDTO = {
  id: E2E_CLARIFY_EVENT_ID,
  user_id: E2E_SESSION.userId,
  raw_text: 'coffee',
  status: 'needs_clarification',
  created_at: '2026-01-01T08:00:00Z',
  updated_at: '2026-01-01T08:00:00Z',
};

/** Clarification read response carrying the seeded question. */
export const E2E_CLARIFICATION: ClarificationDTO = {
  questions: [{ text: E2E_CLARIFY_QUESTION }],
};

/** Resolved event returned after the user answers the clarify question. */
export const E2E_RESOLVED_EVENT: LogEventDTO = {
  id: 'e2e-resolved-event-00000000-0000-0000-0000-000000000000',
  user_id: E2E_SESSION.userId,
  raw_text: 'coffee large',
  status: 'completed',
  created_at: '2026-01-01T08:01:00Z',
  updated_at: '2026-01-01T08:01:00Z',
};

/** Daily summary reflecting the resolved "coffee large" entry (120 kcal). */
export const E2E_RESOLVED_SUMMARY: DailySummaryDTO = {
  date: '2026-01-01',
  intake: { calories: 120, protein_g: 1, carbs_g: 20, fat_g: 3 },
  has_intake: true,
  target: E2E_TARGET,
  exercise: { active_calories: 0 },
};
