/**
 * Synthetic E2E fixtures for the FTY-330 partially-resolved timeline seam.
 *
 * Kept out of the main `fixtures.ts` (which sits at its governance LOC cap) but
 * built from the same shared bases. All data is fabricated for testing only — no
 * real tokens, user logs, or body data.
 */

import type { DailySummaryDTO } from '@/api/dailySummary';
import type { DerivedFoodItemDTO } from '@/api/derivedItems';
import type { ClarificationDTO, LogEventDTO } from '@/api/logEvents';

import {
  E2E_RESOLVED_EVENT_INSTANT,
  E2E_SESSION,
  E2E_TARGET,
} from './fixtures';

/** Stable id for the synthetic partially-resolved (mixed-log) event. */
const E2E_PARTIAL_EVENT_ID =
  'e2e-partial-event-00000000-0000-0000-0000-000000000000';

/**
 * A mixed log whose costable sibling (greek yogurt) is committed and counted
 * while one component (hummus) stays unresolved with an open item-scoped
 * question. The raw phrase never appears as a row on a partial event — the open
 * component is named by the question text instead.
 */
export const E2E_PARTIAL_EVENT: LogEventDTO = {
  id: E2E_PARTIAL_EVENT_ID,
  user_id: E2E_SESSION.userId,
  raw_text: 'greek yogurt and some hummus',
  status: 'partially_resolved',
  created_at: E2E_RESOLVED_EVENT_INSTANT,
  updated_at: E2E_RESOLVED_EVENT_INSTANT,
};

/**
 * The committed, counted sibling the by-date feed carries for the partial event
 * — a normal resolved row (name · kcal · trusted-source provenance icon).
 */
export const E2E_PARTIAL_RESOLVED_ITEM: DerivedFoodItemDTO = {
  item_type: 'food',
  id: 'e2e-partial-item-00000000-0000-0000-0000-000000000000',
  user_id: E2E_SESSION.userId,
  log_event_id: E2E_PARTIAL_EVENT_ID,
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
  created_at: E2E_RESOLVED_EVENT_INSTANT,
  updated_at: E2E_RESOLVED_EVENT_INSTANT,
  source: {
    source_type: 'trusted_nutrition_database',
    label: 'USDA',
    ref: 'usda_fdc:171284',
  },
  is_edited: false,
};

/** The open component's question text — names the component, never the raw phrase. */
const E2E_PARTIAL_QUESTION = 'How much hummus?';

/** Stable id of the open item-scoped question (the answer round-trip key). */
const E2E_PARTIAL_QUESTION_ID =
  'e2e-partial-question-00000000-0000-0000-0000-000000000000';

/** The status-gated clarification read for the partial event's open component. */
export const E2E_PARTIAL_CLARIFICATION: ClarificationDTO = {
  questions: [
    {
      id: E2E_PARTIAL_QUESTION_ID,
      text: E2E_PARTIAL_QUESTION,
      options: ['2 tbsp', '1/4 cup'],
    },
  ],
};

/**
 * Daily summary for the partial day: the committed sibling counts immediately
 * (140 kcal in intake) while the open component contributes one uncounted unit
 * (`daily-summary.md` → `uncounted_entries`), so the hero shows real progress.
 */
export const E2E_PARTIAL_SUMMARY: DailySummaryDTO = {
  date: '2026-01-01',
  intake: { calories: 140, protein_g: 20, carbs_g: 9, fat_g: 4 },
  has_intake: true,
  uncounted_entries: 1,
  target: E2E_TARGET,
  exercise: { active_calories: 0 },
};
