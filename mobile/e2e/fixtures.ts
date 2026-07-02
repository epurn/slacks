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

/** Stable id of the seeded clarification question — the key the answer round-trip references (FTY-170). */
export const E2E_CLARIFY_QUESTION_ID =
  'e2e-clarify-question-00000000-0000-0000-0000-000000000000';

/**
 * Candidate quick-pick options the clarify sheet renders as one-tap chips
 * (FTY-170). clarify.yaml taps `E2E_CLARIFY_CHIP` to resolve the entry in a
 * single tap — the headline capability this story (FTY-175) wires.
 */
export const E2E_CLARIFY_OPTIONS = ['Small', 'Medium', 'Large'];
export const E2E_CLARIFY_CHIP = 'Large';

/** Synthetic needs_clarification event for the FTY-162 clarify flow. */
export const E2E_CLARIFY_EVENT: LogEventDTO = {
  id: E2E_CLARIFY_EVENT_ID,
  user_id: E2E_SESSION.userId,
  raw_text: 'coffee',
  status: 'needs_clarification',
  created_at: '2026-01-01T08:00:00Z',
  updated_at: '2026-01-01T08:00:00Z',
};

/**
 * Clarification read response carrying the seeded question, its stable id, and
 * candidate quick-pick options (the FTY-170 `{ id, text, options }` shape).
 */
export const E2E_CLARIFICATION: ClarificationDTO = {
  questions: [
    {
      id: E2E_CLARIFY_QUESTION_ID,
      text: E2E_CLARIFY_QUESTION,
      options: E2E_CLARIFY_OPTIONS,
    },
  ],
};

/**
 * The answer round-trip's response (FTY-170): the **same** clarify event,
 * transitioned in place to `processing`. Its id is unchanged (no duplicate row)
 * and its `raw_text` is still 'coffee' (the raw phrase is never mutated by an
 * answer — audit A3) even though the user answered "large".
 */
export const E2E_CLARIFY_PROCESSING_EVENT: LogEventDTO = {
  ...E2E_CLARIFY_EVENT,
  status: 'processing',
  updated_at: '2026-01-01T08:00:01Z',
};

/**
 * Wall-clock label the resolved event must render as in the timeline.
 * clarify.yaml asserts this exact string is visible (and its PM twin is not) —
 * the FTY-174 Hermes meridiem regression guard. 11:14 AM is the story's
 * canonical case: the buggy `toLocaleTimeString(..., { hour12: true })` path
 * rendered it as "11:14 PM" on Hermes.
 */
export const E2E_RESOLVED_EVENT_TIME_LABEL = '11:14 AM';

/**
 * ISO instant for today at 11:14 AM in the *device's own* timezone. Computed
 * with local-time Date setters (no Intl), so the expected "11:14 AM" label
 * holds on any simulator/emulator timezone while the render path under test
 * still goes through Intl on Hermes — keeping the Maestro assertion hermetic
 * without pinning the device clock.
 */
function todayAtDeviceLocal(hour: number, minute: number): string {
  const at = new Date();
  at.setHours(hour, minute, 0, 0);
  return at.toISOString();
}

const E2E_RESOLVED_EVENT_INSTANT = todayAtDeviceLocal(11, 14);

/**
 * The resolved, completed entry the day-list returns after the clarify answer
 * re-estimates the event. Its `raw_text` stays 'coffee' — the answer supplied
 * the "large" detail as structured input, it never rewrote the raw phrase (audit
 * A3). (Distinct id from the needs_clarification event so the FTY-178 smoke
 * flow's second-POST re-submission reconciles without a duplicate-key collision;
 * the clarify flow drops the pre-resolve row on refresh either way.)
 */
export const E2E_RESOLVED_EVENT: LogEventDTO = {
  id: 'e2e-resolved-event-00000000-0000-0000-0000-000000000000',
  user_id: E2E_SESSION.userId,
  raw_text: 'coffee',
  status: 'completed',
  created_at: E2E_RESOLVED_EVENT_INSTANT,
  updated_at: E2E_RESOLVED_EVENT_INSTANT,
};

/** Daily summary reflecting the resolved "coffee" entry (120 kcal). */
export const E2E_RESOLVED_SUMMARY: DailySummaryDTO = {
  date: '2026-01-01',
  intake: { calories: 120, protein_g: 1, carbs_g: 20, fat_g: 3 },
  has_intake: true,
  target: E2E_TARGET,
  exercise: { active_calories: 0 },
};

// ─── FTY-176 failed-parse fixtures ────────────────────────────────────────────

/**
 * The gibberish input the failed-parse flow (failed.yaml) submits. The E2E mock
 * keys the failed-parse branch off this exact `raw_text`, so it never collides
 * with the clarify flow's "coffee" — the two flows share one binary and one mock
 * but drive independent state.
 */
export const E2E_FAILED_RAW_TEXT = 'zxqwvb';

/**
 * Synthetic `failed` event returned for the first submission of the gibberish
 * text. The timeline must render it as the actionable "Couldn't read that" row
 * (Retry + Edit as text), never a static dead end (FTY-176).
 */
export const E2E_FAILED_EVENT: LogEventDTO = {
  id: 'e2e-failed-event-00000000-0000-0000-0000-000000000000',
  user_id: E2E_SESSION.userId,
  raw_text: E2E_FAILED_RAW_TEXT,
  status: 'failed',
  created_at: '2026-01-01T08:00:00Z',
  updated_at: '2026-01-01T08:00:00Z',
};

/**
 * The `pending` event a Retry produces — a genuine fresh attempt (a distinct id
 * from the failed one). The failed row is superseded in place by this pending
 * attempt, so failed.yaml asserts the row becomes "Waiting to estimate".
 */
export const E2E_FAILED_RETRY_EVENT: LogEventDTO = {
  id: 'e2e-failed-retry-00000000-0000-0000-0000-000000000000',
  user_id: E2E_SESSION.userId,
  raw_text: E2E_FAILED_RAW_TEXT,
  status: 'pending',
  created_at: '2026-01-01T08:01:00Z',
  updated_at: '2026-01-01T08:01:00Z',
};
