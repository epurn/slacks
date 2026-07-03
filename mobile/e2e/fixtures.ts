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
import type { WeightEntryDTO } from '@/api/weightEntries';
import type { SavedFoodDTO } from '@/api/savedFoods';
import type { SourceCandidate } from '@/api/corrections';
import type { DerivedFoodItemDTO } from '@/api/derivedItems';

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
 * Synthetic needs_clarification event for the FTY-162 clarify flow. Pinned to
 * today-at-11:14 device local so the same entry — id and `created_at` are both
 * immutable through the clarify resolve — renders the FTY-174 meridiem-guard
 * label after it completes.
 */
export const E2E_CLARIFY_EVENT: LogEventDTO = {
  id: E2E_CLARIFY_EVENT_ID,
  user_id: E2E_SESSION.userId,
  raw_text: 'coffee',
  status: 'needs_clarification',
  created_at: E2E_RESOLVED_EVENT_INSTANT,
  updated_at: E2E_RESOLVED_EVENT_INSTANT,
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
};

/**
 * The completed entry the day-list returns after the clarify answer
 * re-estimates the event. It is the **same** event — same id (no duplicate
 * row), same `raw_text` ('coffee'; the answer supplied the "large" detail as
 * structured input and never rewrote the raw phrase — audit A3), same
 * `created_at` — now terminal. clarify.yaml's post-refresh assertions run
 * against this fixture, so the Maestro flow genuinely proves same-entry,
 * no-duplicate resolution end-to-end.
 */
export const E2E_CLARIFY_RESOLVED_EVENT: LogEventDTO = {
  ...E2E_CLARIFY_EVENT,
  status: 'completed',
};

/**
 * The completed entry the FTY-178 smoke flow's second-POST re-submission
 * returns. Only that flow reaches the resolved phase via a plain create, which
 * genuinely makes a new event server-side — hence the distinct id (it also
 * keeps the optimistic-reconcile from colliding with the phase-1 clarify row
 * already in the timeline). The clarify flow never sees this fixture: its
 * refresh serves E2E_CLARIFY_RESOLVED_EVENT, the same-id proof.
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

// ─── FTY-187 Trends weight + adherence fixtures ───────────────────────────────
//
// The Trends screen queries a live date window derived from the device's own
// clock (rangeBounds(range, new Date())), so these fixtures are built from the
// requested window rather than pinned to fixed dates — the data always lands
// inside range and the chart, headline, and adherence card render real content.
// A data-starved Trends (empty/error cards) is an explicit testing-standards
// failure, so trends.yaml asserts the populated end state, not a placeholder.

/**
 * Shift a YYYY-MM-DD string by whole days, UTC-anchored so it never drifts
 * across a DST boundary. Used to derive the fixture dates from the window the
 * Trends screen requests.
 */
function shiftIsoDate(isoDate: string, days: number): string {
  const [y, m, d] = isoDate.split('-').map(Number);
  const at = new Date(Date.UTC(y!, m! - 1, d!));
  at.setUTCDate(at.getUTCDate() + days);
  return at.toISOString().slice(0, 10);
}

/**
 * Every calendar day from `from` through `to` inclusive (oldest first),
 * mirroring the client's buildDayRange so range summaries key onto the strip.
 */
function e2eDayRange(from: string, to: string): string[] {
  const out: string[] = [];
  let cur = from;
  for (let i = 0; i < 400 && cur <= to; i++) {
    out.push(cur);
    cur = shiftIsoDate(cur, 1);
  }
  return out;
}

/**
 * Synthetic weight series for the Trends flow. Dates are anchored to the
 * window's end (`to` — the device's today), so the entries fall inside the live
 * range the screen queries and the multi-point chart + headline delta render
 * real data. A gentle downward EWMA trend keeps the headline delta legible.
 */
export function e2eWeightEntries(to: string): WeightEntryDTO[] {
  const series: readonly (readonly [number, number])[] = [
    [28, 76.2],
    [21, 75.9],
    [14, 75.6],
    [7, 75.2],
    [0, 74.8],
  ];
  return series.map(([daysAgo, weightKg], i) => {
    const date = shiftIsoDate(to, -daysAgo);
    return {
      id: `e2e-weight-${i}`,
      user_id: E2E_SESSION.userId,
      weight_kg: weightKg,
      effective_date: date,
      created_at: `${date}T08:00:00Z`,
      updated_at: `${date}T08:00:00Z`,
    };
  });
}

/**
 * Synthetic daily-summary range for the Trends adherence card. The range
 * endpoint returns a row per calendar day, so this returns one per day in the
 * window: the most recent 12 days carry a target and near-target logged intake
 * (mostly on-target) so the card shows real on-target days, and earlier days
 * are unlogged (`has_intake: false`) exactly like days the server has no
 * finalized data for — dayAdherenceState classifies those as no-data.
 */
export function e2eDailySummaryRange(
  from: string,
  to: string,
): DailySummaryDTO[] {
  const days = e2eDayRange(from, to);
  const total = days.length;
  return days.map((date, i) => {
    const logged = i >= total - 12;
    if (!logged) {
      return {
        date,
        intake: { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 },
        has_intake: false,
        target: null,
        exercise: { active_calories: 0 },
      };
    }
    // Mostly on-target (within ±10% of the 2,000 kcal target); every fifth day
    // off-target, so the card reports a believable on-of-target ratio.
    const offTarget = i % 5 === 0;
    const calories = offTarget ? 1500 : 1980;
    return {
      date,
      intake: {
        calories,
        protein_g: Math.round(calories * 0.075),
        carbs_g: Math.round(calories * 0.1),
        fat_g: Math.round(calories * 0.0325),
      },
      has_intake: true,
      target: E2E_TARGET,
      exercise: { active_calories: 0 },
    };
  });
}

// ─── FTY-183 correction-sheet save-path fixtures ──────────────────────────────
//
// Back the correction.yaml Maestro flow, which drives the CorrectionSheet's
// medium → large detent save path end-to-end. The only E2E-reachable way to put
// a tappable, resolved food item on the Today timeline is the saved-food
// synthetic-item path (TodayScreen selects a saved food from the typeahead, then
// inserts a resolved synthetic item on submit — server-side item hydration is a
// later story). So the flow: pick this saved food → its item lands on the
// timeline → tap it to open the sheet at the medium detent → open Change-match
// (the sheet expands to the large detent) → pick a candidate → the re-resolve
// commits and the item re-renders with the new source/values.

/**
 * The saved food the correction flow selects from the composer typeahead. Its
 * name is prefix-searchable ("Chicken…") so the FTY-053 suggestion chip appears
 * as the user types. Submitting it inserts a resolved synthetic item carrying
 * these values, which renders as a tappable timeline row.
 */
export const E2E_SAVED_FOOD: SavedFoodDTO = {
  id: 'e2e-saved-food-00000000-0000-0000-0000-000000000000',
  user_id: E2E_SESSION.userId,
  name: 'Chicken burrito bowl',
  calories: 640,
  protein_g: 42,
  carbs_g: 56,
  fat_g: 22,
  serving_size: 1,
  serving_unit: 'bowl',
  source: 'saved_from_correction',
  created_at: '2026-01-01T08:00:00Z',
  updated_at: '2026-01-01T08:00:00Z',
};

/**
 * The derived-item id TodayScreen builds for the saved-food synthetic item
 * (`saved-${savedFood.id}`). The re-resolve response echoes this id so the
 * edit reconciles back onto the same timeline row.
 */
export const E2E_SAVED_FOOD_ITEM_ID = `saved-${E2E_SAVED_FOOD.id}`;

/** Stable id for the completed log event the saved-food submit resolves to. */
export const E2E_SAVED_FOOD_EVENT_ID =
  'e2e-saved-food-event-00000000-0000-0000-0000-000000000000';

/**
 * The completed log event GET /log-events returns once the saved food is
 * submitted. Keyed on the saved food's name so it drives state independently of
 * the clarify ("coffee") and failed-parse (gibberish) phase machines. The
 * timeline renders the client-built synthetic item; this event only has to exist
 * and stay `completed` under a stable id so a poll never drops the row.
 */
export const E2E_SAVED_FOOD_EVENT: LogEventDTO = {
  id: E2E_SAVED_FOOD_EVENT_ID,
  user_id: E2E_SESSION.userId,
  raw_text: E2E_SAVED_FOOD.name,
  status: 'completed',
  created_at: '2026-01-01T12:00:00Z',
  updated_at: '2026-01-01T12:00:00Z',
};

/**
 * The alternative source the Change-match panel offers (FTY-093). Its
 * accessibility label ("Select {name}, {kcal} kcal per 100g") is the tappable
 * candidate row the flow picks to re-resolve the item.
 */
export const E2E_SOURCE_CANDIDATE: SourceCandidate = {
  source_type: 'trusted_nutrition_database',
  source_ref: 'usda_fdc:171477',
  name: 'Chicken, grilled, USDA',
  basis: 'per_100g',
  calories: 165,
  protein_g: 31,
  carbs_g: 0,
  fat_g: 3.6,
};

/**
 * The item after re-resolving to the USDA candidate: the **same** id and
 * log_event_id (so it reconciles back onto the same row — no duplicate), an
 * honest new provenance label ("USDA"), and server-recomputed values at the
 * current portion. Its distinctive `calories` (415, clearly different from the
 * saved food's 640) is what correction.yaml asserts to prove the re-resolve
 * committed and the sheet + timeline re-rendered the new values.
 */
export const E2E_RERESOLVED_ITEM: DerivedFoodItemDTO = {
  item_type: 'food',
  id: E2E_SAVED_FOOD_ITEM_ID,
  user_id: E2E_SESSION.userId,
  log_event_id: E2E_SAVED_FOOD_EVENT_ID,
  name: E2E_SOURCE_CANDIDATE.name,
  quantity_text: `${E2E_SAVED_FOOD.serving_size} ${E2E_SAVED_FOOD.serving_unit}`,
  unit: E2E_SAVED_FOOD.serving_unit,
  amount: E2E_SAVED_FOOD.serving_size,
  status: 'resolved',
  grams: null,
  calories: 415,
  protein_g: 78,
  carbs_g: 0,
  fat_g: 9,
  calories_estimated: E2E_SAVED_FOOD.calories,
  protein_g_estimated: E2E_SAVED_FOOD.protein_g,
  carbs_g_estimated: E2E_SAVED_FOOD.carbs_g,
  fat_g_estimated: E2E_SAVED_FOOD.fat_g,
  source: {
    source_type: 'trusted_nutrition_database',
    label: 'USDA',
    ref: E2E_SOURCE_CANDIDATE.source_ref,
  },
  is_edited: false,
  created_at: '2026-01-01T08:00:00Z',
  updated_at: '2026-01-01T12:05:00Z',
};
