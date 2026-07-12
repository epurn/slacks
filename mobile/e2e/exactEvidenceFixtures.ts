/**
 * FTY-313: synthetic fixtures for the `Make it exact` exact-evidence visual audit.
 *
 * The FTY-311/312 exact-evidence sub-flow (barcode/label → preview → apply
 * in place) is component-local state inside the correction sheet with no route
 * param or tap-free entry point — and at the sheet's large, dimmed detent iOS
 * exposes no in-modal content to the accessibility tree (ratified FTY-272), so
 * a scripted Maestro tap cannot drive the preview/error/label sub-steps on iOS.
 * These fixtures let the correction visual-review seam
 * (`components/correction/visualReviewSeam.ts`) open each exact-flow sub-state
 * *directly* over a synthetic entry — the same "open the sub-state, never a
 * scripted tap" contract every other FTY-247 preset uses.
 *
 * All data is fabricated for testing only: no real tokens, user logs, body data,
 * barcode values, provider payloads, or images. These constants live in the
 * public repo and must never carry secrets or private data. Kept in this
 * dedicated module (not the shared `fixtures.ts`) so the exact-flow data lands
 * without pushing that file over its LOC budget.
 */

import type { DerivedFoodItemDTO } from '@/api/derivedItems';
import type {
  ExactEvidenceExactProposal,
  ExactEvidenceFallbackProposal,
} from '@/api/exactEvidence';
import type { DailySummaryDTO } from '@/api/dailySummary';
import type { LogEventDTO, LogEventEntryDTO } from '@/api/logEvents';

import { E2E_SESSION, E2E_TARGET } from './fixtures';

/** The user's original phrase, shown quoted in the correction sheet evidence block. */
export const E2E_EXACT_RAW_TEXT = 'peanut butter toast';

/** Stable id for the exact-flow event (independent of the other flows' ids). */
const E2E_EXACT_EVENT_ID = 'e2e-exact-event-00000000-0000-0000-0000-000000000000';

/** Stable id for the exact-flow derived item (the exact-upgrade target). */
const E2E_EXACT_ITEM_ID = 'e2e-exact-item-00000000-0000-0000-0000-000000000000';

/** The completed event both the eligible and applied item hang from. */
export const E2E_EXACT_EVENT: LogEventDTO = {
  id: E2E_EXACT_EVENT_ID,
  user_id: E2E_SESSION.userId,
  raw_text: E2E_EXACT_RAW_TEXT,
  status: 'completed',
  created_at: '2026-01-01T08:10:00Z',
  updated_at: '2026-01-01T08:10:00Z',
};

/**
 * The low-trust ("≈ Rough estimate", `model_prior`) food item the eligible
 * presets open over. `isExactUpgradeEligible` returns true for it, so the
 * `Make it exact` nudge is visible — the eligible half of the visibility
 * criterion.
 */
export const E2E_EXACT_ELIGIBLE_ITEM: DerivedFoodItemDTO = {
  item_type: 'food',
  id: E2E_EXACT_ITEM_ID,
  user_id: E2E_SESSION.userId,
  log_event_id: E2E_EXACT_EVENT_ID,
  name: 'Peanut butter toast',
  quantity_text: '1 slice',
  unit: 'slice',
  amount: 1,
  status: 'resolved',
  grams: 36,
  calories: 220,
  protein_g: 8,
  carbs_g: 24,
  fat_g: 11,
  calories_estimated: 220,
  protein_g_estimated: 8,
  carbs_g_estimated: 24,
  fat_g_estimated: 11,
  created_at: '2026-01-01T08:10:00Z',
  updated_at: '2026-01-01T08:10:00Z',
  source: { source_type: 'model_prior', label: 'Rough estimate', ref: 'model_prior:1' },
  is_edited: false,
};

/**
 * The same item after an exact-evidence proposal has been applied in place: now
 * source-backed (`product_database` · Open Food Facts) with the proposal's
 * facts. Same id + event as the eligible item — an in-place upgrade, never a new
 * row. `isExactUpgradeEligible` is now false, so the `Make it exact` nudge is
 * gone: the applied end state.
 */
export const E2E_EXACT_APPLIED_ITEM: DerivedFoodItemDTO = {
  ...E2E_EXACT_ELIGIBLE_ITEM,
  calories: 210,
  protein_g: 9,
  carbs_g: 22,
  fat_g: 10,
  calories_estimated: 210,
  protein_g_estimated: 9,
  carbs_g_estimated: 22,
  fat_g_estimated: 10,
  updated_at: '2026-01-01T08:12:00Z',
  source: { source_type: 'product_database', label: 'Open Food Facts', ref: 'off:0123456789012' },
  is_edited: false,
};

/** By-date feed row + daily summary for the eligible (pre-upgrade) item. */
export const E2E_EXACT_ELIGIBLE_ENTRY: LogEventEntryDTO = {
  event: E2E_EXACT_EVENT,
  items: [E2E_EXACT_ELIGIBLE_ITEM],
};

export const E2E_EXACT_ELIGIBLE_SUMMARY: DailySummaryDTO = {
  date: '2026-01-01',
  intake: { calories: 220, protein_g: 8, carbs_g: 24, fat_g: 11 },
  has_intake: true,
  uncounted_entries: 0,
  target: E2E_TARGET,
  exercise: { active_calories: 0 },
};

/** By-date feed row + daily summary for the applied (post-upgrade) item. */
export const E2E_EXACT_APPLIED_ENTRY: LogEventEntryDTO = {
  event: E2E_EXACT_EVENT,
  items: [E2E_EXACT_APPLIED_ITEM],
};

export const E2E_EXACT_APPLIED_SUMMARY: DailySummaryDTO = {
  date: '2026-01-01',
  intake: { calories: 210, protein_g: 9, carbs_g: 22, fat_g: 10 },
  has_intake: true,
  uncounted_entries: 0,
  target: E2E_TARGET,
  exercise: { active_calories: 0 },
};

/**
 * The exact barcode proposal the preview renders: resolved through its exact
 * source (`product_database` · Open Food Facts), applyable, costable at the
 * current amount. The preview is visually the trusted "Exact match · …" state.
 */
export const E2E_EXACT_BARCODE_EXACT_PROPOSAL: ExactEvidenceExactProposal = {
  proposal_ref: 'e2e-exact-proposal-ref-not-a-real-ref',
  kind: 'barcode',
  can_cost_current_amount: true,
  quality: 'exact',
  failure_reason: null,
  preview: {
    source: { source_type: 'product_database', label: 'Open Food Facts', ref: 'off:0123456789012' },
    calories: 210,
    protein_g: 9,
    carbs_g: 22,
    fat_g: 10,
    amount: 1,
    serving_label: '1 slice (36 g)',
  },
};

/**
 * The fallback barcode proposal the preview renders: exact evidence failed
 * (`barcode_no_match`), so an honestly-rough `model_prior` result is offered —
 * never labelled exact. The preview shows the "≈ Rough fallback · …" box + the
 * fallback notice, visually distinct from the exact state above.
 */
export const E2E_EXACT_BARCODE_FALLBACK_PROPOSAL: ExactEvidenceFallbackProposal = {
  proposal_ref: 'e2e-fallback-proposal-ref-not-a-real-ref',
  kind: 'barcode',
  can_cost_current_amount: true,
  quality: 'fallback',
  failure_reason: 'barcode_no_match',
  preview: {
    source: { source_type: 'model_prior', label: 'Rough estimate', ref: 'model_prior:1' },
    calories: 235,
    protein_g: 8,
    carbs_g: 26,
    fat_g: 12,
    amount: 1,
    serving_label: null,
  },
};

/**
 * The no-proposal/error copy the error step shows for a barcode attempt that
 * produced neither exact evidence nor a rough fallback. Mirrors the private
 * `noProposalNotice('barcode')` in `useExactEvidence`; the seam seeds it as the
 * error message so the calm, actionable error state renders with no live call.
 */
export const E2E_EXACT_NO_PROPOSAL_MESSAGE =
  'No exact match from that barcode, and no rough fallback either. Try again, change the match, or edit it manually.';

/**
 * A 1×1 transparent PNG data URI the label-capture preview's `takePhoto` seam
 * returns, so the save-photo preview renders on the camera-less simulator
 * without a real capture. The preview's fixed dark placeholder fills the frame;
 * the point of the shot is the default-off "Save this photo" toggle, not the
 * pixels. Fabricated for testing only — no real image.
 */
export const E2E_EXACT_LABEL_PHOTO_URI =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==';
