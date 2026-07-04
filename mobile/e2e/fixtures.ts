/**
 * Synthetic E2E fixtures (FTY-160, FTY-162).
 *
 * All data is fabricated for testing only — no real tokens, user logs, or body
 * data. These constants live in the public repo and must never carry secrets,
 * machine paths, or private data.
 */

import { type PermissionResponse, PermissionStatus } from 'expo';

import type { SessionRecord } from '@/state/session';
import type { ProfileDTO } from '@/api/profile';
import type { DailySummaryDTO, TargetReadModel } from '@/api/dailySummary';
import type { ActiveGoal, GoalTargetResponse } from '@/api/goals';
import type {
  LogEventDTO,
  LogEventEntryDTO,
  ClarificationDTO,
} from '@/api/logEvents';
import type { DerivedFoodItemDTO } from '@/api/derivedItems';
import type { WeightEntryDTO } from '@/api/weightEntries';
import type { SavedFoodDTO } from '@/api/savedFoods';
import type { SourceCandidate } from '@/api/corrections';

export const E2E_SERVER_URL = 'http://localhost:8000';

/**
 * Granted camera-permission response for the barcode-scanner E2E flow (FTY-194).
 *
 * The iOS simulator has no camera, so `useCameraPermissions` never leaves the
 * `undetermined` state and the scanner's granted chrome — the reticle, torch,
 * and the "Type it instead" fallback — never renders. This synthetic granted
 * response is the hermetic equivalent of the OS permission grant (mirroring the
 * Reduce Motion override in launchMode.ts): it lets `barcode-manual-entry.yaml`
 * drive the real Today → scanner → "Type it instead" → pre-filled composer path
 * without a device camera or a flaky system permission dialog. Fabricated for
 * testing only; it carries no real permission state.
 */
export const E2E_CAMERA_PERMISSION_GRANTED: PermissionResponse = {
  status: PermissionStatus.GRANTED,
  granted: true,
  canAskAgain: true,
  expires: 'never',
};

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

/**
 * Goal + target reveal returned by `POST /goal` (FTY-106). Backs the FTY-182
 * profile flow: saving a goal edit under the native header must resolve to the
 * mini target-reveal, so the E2E mock has to answer the goal create the real
 * `createGoal` client makes. The revealed calories match `E2E_TARGET` (2,000)
 * so the reveal card and the subsequently-refetched target read-model agree.
 */
export const E2E_GOAL_TARGET_RESPONSE: GoalTargetResponse = {
  goal: {
    id: 'e2e-goal-00000000-0000-0000-0000-000000000000',
    user_id: E2E_SESSION.userId,
    start_weight_kg: 75,
    start_date: '2026-01-01',
    target_weight_kg: 72,
    target_date: '2026-04-01',
    is_active: true,
  },
  target: {
    calories: 2000,
    rmr_kcal: 1600,
    tdee_kcal: 2100,
    direction: 'loss',
    clamped: false,
  },
  provenance: { source: 'derived', basis: 'goal_and_metrics' },
  clamp: { clamped: false, reason: null },
};

/**
 * The returning user's active goal served by `GET /goal` (the FTY-189/FTY-190
 * read model). Direction and pace are each recovered server-side from the
 * persisted trajectory: `loss` matches the seeded goal above (start 75 kg →
 * target 72 kg → a loss trajectory) and `steady` is the band that trajectory was
 * derived from. So a cold-launched Settings screen summarises the real goal as
 * `Goal: Lose · Steady` before any in-session edit, instead of the dead
 * "Active" / neutral "Details unavailable" states FTY-190 removes.
 */
export const E2E_ACTIVE_GOAL: ActiveGoal = {
  direction: 'loss',
  pace: 'steady',
};

/** Zero daily summary for an empty E2E day. */
export const E2E_DAILY_SUMMARY: DailySummaryDTO = {
  date: '2026-01-01',
  intake: { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 },
  has_intake: false,
  uncounted_entries: 0,
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
  uncounted_entries: 0,
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
        uncounted_entries: 0,
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
      uncounted_entries: 0,
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

/**
 * The saved-food item after a Portion (amount) step: the **same** id and
 * log_event_id (reconciles onto the same row), amount stepped from 1 to 1.25
 * bowls, and server-recomputed values scaled from the saved food's per-serving
 * macros (640 kcal → 800 kcal). Its distinctive `calories` (800, distinct from
 * the saved food's 640, the re-resolve's 415, and the estimated-correction
 * item's 175) is what FTY-245's regression guard asserts to prove the
 * saved-food Portion PATCH branch — not the 404 fall-through — handled the
 * commit.
 */
export const E2E_SAVED_FOOD_EDITED_ITEM: DerivedFoodItemDTO = {
  item_type: 'food',
  id: E2E_SAVED_FOOD_ITEM_ID,
  user_id: E2E_SESSION.userId,
  log_event_id: E2E_SAVED_FOOD_EVENT_ID,
  name: E2E_SAVED_FOOD.name,
  quantity_text: '1.25 bowl',
  unit: E2E_SAVED_FOOD.serving_unit,
  amount: 1.25,
  status: 'resolved',
  grams: null,
  calories: 800,
  protein_g: 52.5,
  carbs_g: 70,
  fat_g: 27.5,
  calories_estimated: E2E_SAVED_FOOD.calories,
  protein_g_estimated: E2E_SAVED_FOOD.protein_g,
  carbs_g_estimated: E2E_SAVED_FOOD.carbs_g,
  fat_g_estimated: E2E_SAVED_FOOD.fat_g,
  // Portion (amount) change = provenance-preserving `amount_adjust`, item stays un-edited (docs/contracts/corrections.md).
  is_edited: false,
  created_at: '2026-01-01T08:00:00Z',
  updated_at: '2026-01-01T12:06:00Z',
};

// ─── FTY-181 entry-resolve (beat 1) item-forward fixtures ─────────────────────
//
// The signature entry-resolve beat eases a resolved entry's *value row* in when
// it transitions pending→completed. That value row only renders when the Today
// feed carries the entry's derived items — the item-forward `/log-events/by-date`
// read (FTY-198). These fixtures drive resolve.yaml: a plain text log resolves to
// a pending entry that refreshes to a completed event whose real derived food
// items (name · kcal · provenance) are served by the by-date feed, so the beat's
// value row is reachable on the real screen data path — not injected item props.
// It is intentionally multi-item: the pending skeleton is one row, the first
// resolved item keeps the event-keyed row for the resolve beat, and the second
// resolved item must become its own editable row. Keyed on its own `raw_text` so
// it never collides with the clarify flow's "coffee" or the failed flow's
// gibberish.

/** The input resolve.yaml submits. Distinct from "coffee" and the gibberish text. */
export const E2E_RESOLVE_RAW_TEXT = 'greek yogurt and banana';

/** Stable id for the resolve flow's completed event. */
export const E2E_RESOLVE_EVENT_ID =
  'e2e-resolve-event-00000000-0000-0000-0000-000000000000';

/** The pending event the resolve flow's POST returns, keeping the skeleton visible. */
export const E2E_RESOLVE_PENDING_EVENT: LogEventDTO = {
  id: E2E_RESOLVE_EVENT_ID,
  user_id: E2E_SESSION.userId,
  raw_text: E2E_RESOLVE_RAW_TEXT,
  status: 'pending',
  created_at: '2026-01-01T09:30:00Z',
  updated_at: '2026-01-01T09:30:00Z',
};

/**
 * The completed event the resolve flow's GET returns after refresh/poll. The
 * client first shows the POST's pending skeleton, then reconciles to this
 * completed event — a genuine pending→completed transition that arms the
 * entry-resolve beat.
 */
export const E2E_RESOLVE_EVENT: LogEventDTO = {
  id: E2E_RESOLVE_EVENT_ID,
  user_id: E2E_SESSION.userId,
  raw_text: E2E_RESOLVE_RAW_TEXT,
  status: 'completed',
  created_at: '2026-01-01T09:30:00Z',
  updated_at: '2026-01-01T09:30:00Z',
};

/**
 * The first resolved derived food item the by-date feed carries for the resolve
 * event. Its row keeps the event-keyed test id through the pending→completed
 * resolve while `E2E_RESOLVE_EXTRA_ITEM` mounts as a normal secondary row.
 */
export const E2E_RESOLVE_ITEM: DerivedFoodItemDTO = {
  item_type: 'food',
  id: 'e2e-resolve-item-00000000-0000-0000-0000-000000000000',
  user_id: E2E_SESSION.userId,
  log_event_id: E2E_RESOLVE_EVENT_ID,
  name: 'Greek yogurt',
  quantity_text: '1 cup',
  unit: 'cup',
  amount: 1,
  status: 'resolved',
  grams: 245,
  calories: 140,
  protein_g: 20,
  carbs_g: 9,
  fat_g: 4,
  calories_estimated: 140,
  protein_g_estimated: 20,
  carbs_g_estimated: 9,
  fat_g_estimated: 4,
  created_at: '2026-01-01T09:30:00Z',
  updated_at: '2026-01-01T09:30:00Z',
  source: {
    source_type: 'trusted_nutrition_database',
    label: 'USDA',
    ref: 'usda_fdc:171284',
  },
  is_edited: false,
};

/** The second resolved item, rendered as its own row after the resolve beat. */
export const E2E_RESOLVE_EXTRA_ITEM: DerivedFoodItemDTO = {
  item_type: 'food',
  id: 'e2e-resolve-item-extra-00000000-0000-0000-0000-000000000000',
  user_id: E2E_SESSION.userId,
  log_event_id: E2E_RESOLVE_EVENT_ID,
  name: 'Banana',
  quantity_text: '1 medium',
  unit: 'medium',
  amount: 1,
  status: 'resolved',
  grams: 118,
  calories: 105,
  protein_g: 1,
  carbs_g: 27,
  fat_g: 0,
  calories_estimated: 105,
  protein_g_estimated: 1,
  carbs_g_estimated: 27,
  fat_g_estimated: 0,
  created_at: '2026-01-01T09:30:00Z',
  updated_at: '2026-01-01T09:30:00Z',
  source: {
    source_type: 'trusted_nutrition_database',
    label: 'USDA',
    ref: 'usda_fdc:173944',
  },
  is_edited: false,
};

/** The item-forward day row the by-date feed returns once the entry resolves. */
export const E2E_RESOLVE_ENTRY: LogEventEntryDTO = {
  event: E2E_RESOLVE_EVENT,
  items: [E2E_RESOLVE_ITEM, E2E_RESOLVE_EXTRA_ITEM],
};

/** Daily summary reflecting the resolved "greek yogurt and banana" entry. */
export const E2E_RESOLVE_SUMMARY: DailySummaryDTO = {
  date: '2026-01-01',
  intake: { calories: 245, protein_g: 21, carbs_g: 36, fat_g: 4 },
  has_intake: true,
  uncounted_entries: 0,
  target: E2E_TARGET,
  exercise: { active_calories: 0 },
};

// ─── FTY-185 tab-bar occlusion fixtures ──────────────────────────────────────
//
// The tab bar is a floating, blurred `.ultraThin` overlay (`position: 'absolute'`)
// and the Today timeline scrolls *beneath* it, dimming into the app-drawn
// `TabBarScrim` fade before its rows reach the tab labels. Proving that on the
// running app needs a timeline tall enough to actually scroll under the bar, so
// this seed resolves to one completed event carrying a long list of derived
// items — one timeline row each — which `tab-bar-occlusion.yaml` scrolls while
// asserting the tab bar and its dimming scrim stay pinned over the content.
// Keyed on its own raw_text so it never disturbs the clarify / resolve /
// correction / target phase machines.

export const E2E_OCCLUSION_RAW_TEXT = 'big mixed plate';

/** Stable id for the occlusion flow's completed event. */
export const E2E_OCCLUSION_EVENT_ID =
  'e2e-occlusion-event-00000000-0000-0000-0000-000000000000';

/** The pending event the occlusion flow's POST returns, keeping the skeleton visible. */
export const E2E_OCCLUSION_PENDING_EVENT: LogEventDTO = {
  id: E2E_OCCLUSION_EVENT_ID,
  user_id: E2E_SESSION.userId,
  raw_text: E2E_OCCLUSION_RAW_TEXT,
  status: 'pending',
  created_at: '2026-01-01T09:30:00Z',
  updated_at: '2026-01-01T09:30:00Z',
};

/** The completed event the occlusion flow's GET returns after pull-to-refresh. */
export const E2E_OCCLUSION_EVENT: LogEventDTO = {
  id: E2E_OCCLUSION_EVENT_ID,
  user_id: E2E_SESSION.userId,
  raw_text: E2E_OCCLUSION_RAW_TEXT,
  status: 'completed',
  created_at: '2026-01-01T09:30:00Z',
  updated_at: '2026-01-01T09:30:00Z',
};

/**
 * A long, distinct list of resolved foods, deliberately more rows than fit on a
 * single simulator screen so the timeline genuinely scrolls beneath the floating
 * tab bar. `E2E_OCCLUSION_ITEMS` maps each into a full `DerivedFoodItemDTO`; the
 * first ("Scrambled eggs") anchors the top of the list and the last ("Banana")
 * is only reachable after scrolling content under the bar.
 */
const E2E_OCCLUSION_FOODS: readonly { name: string; calories: number }[] = [
  { name: 'Scrambled eggs', calories: 180 },
  { name: 'Whole-wheat toast', calories: 140 },
  { name: 'Greek yogurt', calories: 120 },
  { name: 'Blueberries', calories: 60 },
  { name: 'Grilled chicken', calories: 220 },
  { name: 'Brown rice', calories: 210 },
  { name: 'Steamed broccoli', calories: 55 },
  { name: 'Olive oil drizzle', calories: 90 },
  { name: 'Almonds', calories: 160 },
  { name: 'Apple', calories: 95 },
  { name: 'Dark chocolate', calories: 170 },
  { name: 'Banana', calories: 105 },
];

/** The resolved derived food items the by-date feed carries for the occlusion event. */
export const E2E_OCCLUSION_ITEMS: DerivedFoodItemDTO[] = E2E_OCCLUSION_FOODS.map(
  (food, i): DerivedFoodItemDTO => ({
    item_type: 'food',
    id: `e2e-occlusion-item-${String(i).padStart(2, '0')}-0000-0000-0000-000000000000`,
    user_id: E2E_SESSION.userId,
    log_event_id: E2E_OCCLUSION_EVENT_ID,
    name: food.name,
    quantity_text: '1 serving',
    unit: 'serving',
    amount: 1,
    status: 'resolved',
    grams: 100,
    calories: food.calories,
    protein_g: 5,
    carbs_g: 15,
    fat_g: 4,
    calories_estimated: food.calories,
    protein_g_estimated: 5,
    carbs_g_estimated: 15,
    fat_g_estimated: 4,
    created_at: '2026-01-01T09:30:00Z',
    updated_at: '2026-01-01T09:30:00Z',
    source: {
      source_type: 'trusted_nutrition_database',
      label: 'USDA',
      ref: `usda_fdc:occlusion-${i}`,
    },
    is_edited: false,
  }),
);

/** The item-forward day row the by-date feed returns once the occlusion seed resolves. */
export const E2E_OCCLUSION_ENTRY: LogEventEntryDTO = {
  event: E2E_OCCLUSION_EVENT,
  items: E2E_OCCLUSION_ITEMS,
};

/** Total calories across the occlusion foods (kept in sync with the list above). */
export const E2E_OCCLUSION_TOTAL_CALORIES = E2E_OCCLUSION_FOODS.reduce(
  (sum, food) => sum + food.calories,
  0,
);

/** Daily summary reflecting the resolved multi-item "big mixed plate" entry. */
export const E2E_OCCLUSION_SUMMARY: DailySummaryDTO = {
  date: '2026-01-01',
  intake: {
    calories: E2E_OCCLUSION_TOTAL_CALORIES,
    protein_g: 60,
    carbs_g: 180,
    fat_g: 48,
  },
  has_intake: true,
  uncounted_entries: 0,
  target: E2E_TARGET,
  exercise: { active_calories: 0 },
};

// ─── FTY-181 correction-saved (beat 2) fixtures ───────────────────────────────
//
// The correction-saved beat fires once per successful correction commit. To
// reach it on the real screen a resolved value row must be tappable, the
// correction sheet must open against it, and an amount step must commit a new
// server value — the visible confirmation the beat rides. correction-beat.yaml drives
// exactly that: log "oatmeal" → it resolves with a real 140-kcal item on the
// by-date feed → tap the row → step the portion up → the sheet shows the
// server-recomputed 175 kcal (the commit the beat's haptic accompanies). Keyed on
// its own raw_text so it stays independent of the resolve/clarify/failed flows.

/** The input correction-beat.yaml submits. Distinct from every other flow's text. */
export const E2E_CORRECTION_RAW_TEXT = 'oatmeal';

/** Stable id for the correction flow's completed event. */
export const E2E_CORRECTION_EVENT_ID =
  'e2e-correction-event-00000000-0000-0000-0000-000000000000';

/** Stable id for the correction flow's derived item (the PATCH target). */
export const E2E_CORRECTION_ITEM_ID =
  'e2e-correction-item-00000000-0000-0000-0000-000000000000';

/** The completed event the correction flow's POST returns (pending→completed). */
export const E2E_CORRECTION_EVENT: LogEventDTO = {
  id: E2E_CORRECTION_EVENT_ID,
  user_id: E2E_SESSION.userId,
  raw_text: E2E_CORRECTION_RAW_TEXT,
  status: 'completed',
  created_at: '2026-01-01T07:15:00Z',
  updated_at: '2026-01-01T07:15:00Z',
};

/**
 * The resolved derived item the by-date feed carries for the correction event.
 * ItemTimelineRow renders its accessibility label as "Oatmeal, 140 kcal" — the
 * row correction-beat.yaml taps to open the correction sheet.
 */
export const E2E_CORRECTION_ITEM: DerivedFoodItemDTO = {
  item_type: 'food',
  id: E2E_CORRECTION_ITEM_ID,
  user_id: E2E_SESSION.userId,
  log_event_id: E2E_CORRECTION_EVENT_ID,
  name: 'Oatmeal',
  quantity_text: '1 cup',
  unit: 'cup',
  amount: 1,
  status: 'resolved',
  grams: 234,
  calories: 140,
  protein_g: 5,
  carbs_g: 27,
  fat_g: 3,
  calories_estimated: 140,
  protein_g_estimated: 5,
  carbs_g_estimated: 27,
  fat_g_estimated: 3,
  created_at: '2026-01-01T07:15:00Z',
  updated_at: '2026-01-01T07:15:00Z',
  source: {
    source_type: 'trusted_nutrition_database',
    label: 'USDA',
    ref: 'usda_fdc:169705',
  },
  is_edited: false,
};

/** The item-forward day row the by-date feed returns for the correction entry. */
export const E2E_CORRECTION_ENTRY: LogEventEntryDTO = {
  event: E2E_CORRECTION_EVENT,
  items: [E2E_CORRECTION_ITEM],
};

/** Daily summary reflecting the correction flow's pre-edit oatmeal entry. */
export const E2E_CORRECTION_SUMMARY: DailySummaryDTO = {
  date: '2026-01-01',
  intake: { calories: 140, protein_g: 5, carbs_g: 27, fat_g: 3 },
  has_intake: true,
  uncounted_entries: 0,
  target: E2E_TARGET,
  exercise: { active_calories: 0 },
};

/**
 * The item the PATCH /derived-items/food/{id} returns after an amount step — the
 * server-recomputed portion (1.25 cups → 175 kcal, `is_edited: true`). The
 * correction sheet swaps this in and the 175-kcal value is what correction-beat.yaml
 * asserts: the correction committed on the real data path, so the beat fired.
 */
export const E2E_CORRECTION_EDITED_ITEM: DerivedFoodItemDTO = {
  ...E2E_CORRECTION_ITEM,
  quantity_text: '1.25 cup',
  amount: 1.25,
  calories: 175,
  protein_g: 6,
  carbs_g: 34,
  fat_g: 4,
  calories_estimated: 175,
  protein_g_estimated: 6,
  carbs_g_estimated: 34,
  fat_g_estimated: 4,
  is_edited: true,
  updated_at: '2026-01-01T07:16:00Z',
};

// ─── FTY-181 target-reached (beat 3) fixtures ─────────────────────────────────
//
// The target-reached beat fires once when the day's intake crosses the calorie
// target — a live crossing, never on an app opened already-over. target.yaml
// proves the crossing is reachable on the real screen: the hero mounts on the
// empty day (0 of 2,000 kcal → seeds "not yet reached"), a single large log
// resolves, and the summary poll lands over target so the hero flips to its
// over-budget end state (the visible companion of the beat). Keyed on its own
// raw_text, independent of the other flows.

/** The input target.yaml submits — a large entry that crosses the 2,000 target. */
export const E2E_TARGET_RAW_TEXT = 'holiday roast dinner';

/** Stable id for the target flow's completed event. */
export const E2E_TARGET_EVENT_ID =
  'e2e-target-event-00000000-0000-0000-0000-000000000000';

/** The completed event the target flow's POST returns (pending→completed). */
export const E2E_TARGET_EVENT: LogEventDTO = {
  id: E2E_TARGET_EVENT_ID,
  user_id: E2E_SESSION.userId,
  raw_text: E2E_TARGET_RAW_TEXT,
  status: 'completed',
  created_at: '2026-01-01T18:00:00Z',
  updated_at: '2026-01-01T18:00:00Z',
};

/**
 * The resolved derived item the by-date feed carries for the target event — a
 * 2,100-kcal entry that pushes the day from 0 to over the 2,000-kcal target.
 */
export const E2E_TARGET_ITEM: DerivedFoodItemDTO = {
  item_type: 'food',
  id: 'e2e-target-item-00000000-0000-0000-0000-000000000000',
  user_id: E2E_SESSION.userId,
  log_event_id: E2E_TARGET_EVENT_ID,
  name: 'Holiday roast dinner',
  quantity_text: '1 plate',
  unit: 'plate',
  amount: 1,
  status: 'resolved',
  grams: 900,
  calories: 2100,
  protein_g: 120,
  carbs_g: 150,
  fat_g: 90,
  calories_estimated: 2100,
  protein_g_estimated: 120,
  carbs_g_estimated: 150,
  fat_g_estimated: 90,
  created_at: '2026-01-01T18:00:00Z',
  updated_at: '2026-01-01T18:00:00Z',
  source: {
    source_type: 'model_prior',
    label: 'Estimated',
    ref: 'model_prior',
  },
  is_edited: false,
};

/** The item-forward day row the by-date feed returns for the target entry. */
export const E2E_TARGET_ENTRY: LogEventEntryDTO = {
  event: E2E_TARGET_EVENT,
  items: [E2E_TARGET_ITEM],
};

/**
 * Daily summary after the large entry resolves: 2,100 kcal against the 2,000
 * target, so the hero crosses into its over-budget state ("2,100 of 2,000 kcal,
 * 100 over budget") — the crossing that arms beat 3.
 */
export const E2E_TARGET_SUMMARY: DailySummaryDTO = {
  date: '2026-01-01',
  intake: { calories: 2100, protein_g: 120, carbs_g: 150, fat_g: 90 },
  has_intake: true,
  uncounted_entries: 0,
  target: E2E_TARGET,
  exercise: { active_calories: 0 },
};
