/**
 * FTY-204: Shared error + format helpers for the correction sheet modules.
 *
 * Extracted from the former monolithic `CorrectionSheet.tsx` so the mode panels,
 * row primitives, and the correction-state hook can share one implementation.
 */

import { CorrectionsApiError } from "@/api/corrections";
import { DerivedItemApiError } from "@/api/derivedItems";
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
