/**
 * FTY-383 unified text+image submission fixtures.
 *
 * The Today composer's attach affordance lets a user type free text and attach a
 * photo, then submit both as one multipart create (`log-event-images.md`).
 * `image-submit.yaml` drives that flow on-device: the user types
 * "2 of these bars", attaches a (hermetic fixture) photo, and taps Add. The
 * multipart POST returns a pending entry (skeleton visible in place), then a
 * pull-to-refresh loads the completed event whose by-date feed carries one
 * resolved item derived from BOTH surfaces — "Protein bar", 2 bars, scaled from
 * the label facts (image) by the stated count (text) — and the day summary
 * counts it. Keyed on the exact typed raw text so it never disturbs the other
 * flow machines.
 *
 * Split from fixtures.ts to keep that module under the code-shape LOC threshold.
 * All data is fabricated for testing only — no real tokens, user logs, or body
 * data.
 */

import type { DailySummaryDTO } from '@/api/dailySummary';
import type { LogEventDTO, LogEventEntryDTO } from '@/api/logEvents';
import type { DerivedFoodItemDTO } from '@/api/derivedItems';

import { E2E_SESSION, E2E_TARGET } from './fixtures';

/** The text the image-submit flow types alongside the attached photo. */
export const E2E_IMAGE_RAW_TEXT = '2 of these bars';

/** Stable id for the image-submit event (skeleton and resolved row share it). */
const E2E_IMAGE_EVENT_ID =
  'e2e-image-event-00000000-0000-0000-0000-000000000000';

/** The pending event the multipart POST returns, keeping the skeleton visible. */
export const E2E_IMAGE_PENDING_EVENT: LogEventDTO = {
  id: E2E_IMAGE_EVENT_ID,
  user_id: E2E_SESSION.userId,
  raw_text: E2E_IMAGE_RAW_TEXT,
  status: 'pending',
  created_at: '2026-01-01T10:00:00Z',
  updated_at: '2026-01-01T10:00:00Z',
};

/** The completed event the GET returns after a pull-to-refresh. */
export const E2E_IMAGE_EVENT: LogEventDTO = {
  ...E2E_IMAGE_PENDING_EVENT,
  status: 'completed',
};

/**
 * The resolved item the by-date feed carries once the mixed entry resolves:
 * derived from both surfaces — the label photo's per-bar facts scaled by the
 * text-stated count of 2 — with label-scan provenance.
 */
const E2E_IMAGE_ITEM: DerivedFoodItemDTO = {
  item_type: 'food',
  id: 'e2e-image-item-00000000-0000-0000-0000-000000000000',
  user_id: E2E_SESSION.userId,
  log_event_id: E2E_IMAGE_EVENT_ID,
  name: 'Protein bar',
  quantity_text: '2 bars',
  unit: 'bar',
  amount: 2,
  status: 'resolved',
  grams: 120,
  calories: 380,
  protein_g: 40,
  carbs_g: 44,
  fat_g: 14,
  calories_estimated: 380,
  protein_g_estimated: 40,
  carbs_g_estimated: 44,
  fat_g_estimated: 14,
  created_at: '2026-01-01T10:00:00Z',
  updated_at: '2026-01-01T10:00:00Z',
  source: {
    source_type: 'user_label',
    label: 'Label scan',
    ref: 'user_label',
  },
  is_edited: false,
};

/** The item-forward day row the by-date feed returns once the entry resolves. */
export const E2E_IMAGE_ENTRY: LogEventEntryDTO = {
  event: E2E_IMAGE_EVENT,
  items: [E2E_IMAGE_ITEM],
};

/** Daily summary counting the resolved "2 of these bars" image-backed entry. */
export const E2E_IMAGE_SUMMARY: DailySummaryDTO = {
  date: '2026-01-01',
  intake: { calories: 380, protein_g: 40, carbs_g: 44, fat_g: 14 },
  has_intake: true,
  uncounted_entries: 0,
  target: E2E_TARGET,
  exercise: { active_calories: 0 },
};
