/**
 * FTY-225 barcode manual-entry fixtures.
 *
 * The barcode scanner's "Type it instead" fallback (FTY-194) seeds the composer
 * with the packaged-food starter ("1 serving of "); the user completes the
 * phrase and submits it like any other log. barcode-manual-entry.yaml drives
 * that seeded phrase to its resolved end state: the POST returns a pending
 * entry (skeleton visible), a pull-to-refresh loads the completed event whose
 * by-date feed carries one resolved packaged-food item — "Greek yogurt",
 * 1 serving, 130 kcal, product-database provenance — and the day summary
 * counts it. Keyed on the exact seeded raw text so it never disturbs the
 * clarify / resolve / correction / target / occlusion machines.
 *
 * Split from fixtures.ts to keep that module under the code-shape LOC
 * threshold. All data is fabricated for testing only — no real tokens, user
 * logs, or body data.
 */

import type { DailySummaryDTO } from '@/api/dailySummary';
import type { LogEventDTO, LogEventEntryDTO } from '@/api/logEvents';
import type { DerivedFoodItemDTO } from '@/api/derivedItems';

import { E2E_SESSION, E2E_TARGET } from './fixtures';

/**
 * The input barcode-manual-entry.yaml submits: the FTY-194 composer seed
 * ("1 serving of ") completed with the typed product name.
 */
export const E2E_BARCODE_RAW_TEXT = '1 serving of greek yogurt';

/** Stable id for the barcode flow's event (skeleton and resolved row share it). */
export const E2E_BARCODE_EVENT_ID =
  'e2e-barcode-event-00000000-0000-0000-0000-000000000000';

/** The pending event the barcode flow's POST returns, keeping the skeleton visible. */
export const E2E_BARCODE_PENDING_EVENT: LogEventDTO = {
  id: E2E_BARCODE_EVENT_ID,
  user_id: E2E_SESSION.userId,
  raw_text: E2E_BARCODE_RAW_TEXT,
  status: 'pending',
  created_at: '2026-01-01T10:00:00Z',
  updated_at: '2026-01-01T10:00:00Z',
};

/** The completed event the barcode flow's GET returns after pull-to-refresh. */
export const E2E_BARCODE_EVENT: LogEventDTO = {
  id: E2E_BARCODE_EVENT_ID,
  user_id: E2E_SESSION.userId,
  raw_text: E2E_BARCODE_RAW_TEXT,
  status: 'completed',
  created_at: '2026-01-01T10:00:00Z',
  updated_at: '2026-01-01T10:00:00Z',
};

/**
 * The resolved packaged-food item the by-date feed carries for the barcode
 * event. Its serving data (`amount: 1`, `unit: 'serving'`, quantity_text
 * "1 serving") is what the detail sheet renders as the item's own serving
 * line — the resolved counterpart of the "1 serving of …" phrase the fallback
 * seeded — and its product-database provenance mirrors a real barcode lookup.
 */
export const E2E_BARCODE_ITEM: DerivedFoodItemDTO = {
  item_type: 'food',
  id: 'e2e-barcode-item-00000000-0000-0000-0000-000000000000',
  user_id: E2E_SESSION.userId,
  log_event_id: E2E_BARCODE_EVENT_ID,
  name: 'Greek yogurt',
  quantity_text: '1 serving',
  unit: 'serving',
  amount: 1,
  status: 'resolved',
  grams: 170,
  calories: 130,
  protein_g: 12,
  carbs_g: 9,
  fat_g: 5,
  calories_estimated: 130,
  protein_g_estimated: 12,
  carbs_g_estimated: 9,
  fat_g_estimated: 5,
  created_at: '2026-01-01T10:00:00Z',
  updated_at: '2026-01-01T10:00:00Z',
  source: {
    source_type: 'product_database',
    label: 'Open Food Facts',
    ref: 'open_food_facts:0894700010137',
  },
  is_edited: false,
};

/** The item-forward day row the by-date feed returns once the barcode entry resolves. */
export const E2E_BARCODE_ENTRY: LogEventEntryDTO = {
  event: E2E_BARCODE_EVENT,
  items: [E2E_BARCODE_ITEM],
};

/** Daily summary counting the resolved "1 serving of greek yogurt" entry. */
export const E2E_BARCODE_SUMMARY: DailySummaryDTO = {
  date: '2026-01-01',
  intake: { calories: 130, protein_g: 12, carbs_g: 9, fat_g: 5 },
  has_intake: true,
  uncounted_entries: 0,
  target: E2E_TARGET,
  exercise: { active_calories: 0 },
};
