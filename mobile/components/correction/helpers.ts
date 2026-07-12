/**
 * FTY-204: Shared error + format helpers for the correction sheet modules.
 *
 * Extracted from the former monolithic `CorrectionSheet.tsx` so the mode panels,
 * row primitives, and the correction-state hook can share one implementation.
 */

import { CorrectionsApiError } from "@/api/corrections";
import { DerivedItemApiError, type DerivedItem } from "@/api/derivedItems";
import { formatValue } from "@/state/derivedItems";

/**
 * Debounce for the Change-match search field. Each keystroke would otherwise
 * trigger a USDA FDC name-search fan-out server-side; waiting for a typing pause
 * keeps provider egress bounded (see evidence-retrieval.md `SLACKS_FDC_MAX_RESULTS`).
 */
export const SEARCH_DEBOUNCE_MS = 300;

/** Map a correction API error to a plain, nonjudgmental message. */
export function messageForError(error: unknown, action: string): string {
  if (error instanceof CorrectionsApiError || error instanceof DerivedItemApiError) {
    return (error as { message: string }).message;
  }
  return `We couldn't ${action}. Check your connection and try again.`;
}

/** Format a numeric amount for display, omitting decimals when integral. */
export function formatAmount(amount: number | null): string {
  if (amount === null) return "—";
  return formatValue(amount);
}

/**
 * FTY-312: which items offer the correction sheet's `Make it exact` entry point.
 *
 * Only **low-trust or incomplete food** items are eligible, derived purely from
 * the fields the public read model already contracts
 * (`docs/contracts/evidence-retrieval.md` → **Eligibility**;
 * `docs/contracts/daily-summary.md` → **`source` descriptor**): the descriptor's
 * `source_type` and `estimate_basis` plus the item's nullable macro facts — no
 * new persisted flag. Exercise items and already source-backed food sources
 * (`user_label`, `product_database`, `trusted_nutrition_database`,
 * `official_source`) are never eligible, so the rendered nudge and the server's
 * propose-time validation (`food-resolution.md`, rejecting an ineligible target
 * with `not_upgradeable`) can never disagree.
 */
export function isExactUpgradeEligible(item: DerivedItem): boolean {
  if (item.item_type !== "food") return false;
  const source = item.source;
  if (!source) return false;
  switch (source.source_type) {
    // Rough/default-prior estimates and searched public-reference estimates.
    case "model_prior":
    case "reference_source":
      return true;
    // A user-stated calorie total is eligible only while its macros are still
    // incomplete — a macro fact unknown/null, or a non-null `estimate_basis`
    // marking a roughly gap-filled macro (FTY-281/FTY-350).
    case "user_text":
      return (
        item.protein_g === null ||
        item.carbs_g === null ||
        item.fat_g === null ||
        (source.estimate_basis ?? null) !== null
      );
    default:
      return false;
  }
}
