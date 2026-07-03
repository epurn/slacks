/**
 * Typed client for the FTY-196 label-proposal confirmation gate, consumed by the
 * confirm-parsed-values sheet (FTY-197).
 *
 * A legible nutrition-label parse lands as an **uncounted proposal** (a
 * `proposed` derived food item that does not count toward totals) rather than an
 * immediately-counted `resolved` item, because "OCR is fallible — Fatty never
 * silently trusts a fallible parse" (`docs/design-philosophy.md`). Two
 * owner-scoped operations from `docs/contracts/label-upload.md` back the sheet:
 *
 * - `getLabelProposal` — `GET .../log-events/{event_id}/label-proposal`: returns
 *   the parsed food values (name/serving, calories, macros) enriched with the
 *   `user_label` "Label scan" source descriptor, or `null` when the event has no
 *   uncounted proposal (never had one, or already confirmed — no status oracle).
 * - `confirmLabelProposal` — `POST .../label-proposal/confirm`: commits the
 *   proposal `proposed → resolved` so it counts. An optional body carries
 *   adjusted values — a changed calorie/macro is the user's own number
 *   (`user_edit`, marks the item edited), an adjusted `amount` is a
 *   provenance-preserving servings rescale; an empty body commits the parse as-is.
 *
 * Both fail closed server-side: a cross-user or nonexistent `event_id` is `404`
 * with no existence oracle. Nutrition values are never logged; errors carry only
 * the HTTP status and the attempted action.
 */

import {
  ApiError,
  authHeaders,
  request,
  userScopedUrl,
} from "@/api/client";
import type { ApiSession } from "@/api/client";
import type { DerivedFoodItemDTO } from "@/api/derivedItems";

/** Raised when a label-proposal API call returns a non-2xx status. */
export class LabelProposalApiError extends ApiError {
  constructor(status: number, message: string) {
    super(status, message);
    this.name = "LabelProposalApiError";
  }
}

function labelProposalError(status: number, action: string): LabelProposalApiError {
  const message =
    status === 401
      ? "Your session has expired. Sign in again to keep logging."
      : status === 404
        ? "We couldn't find that label entry."
        : status === 422
          ? "That value couldn't be applied. Check the number and try again."
          : `Could not ${action} (status ${status}).`;
  return new LabelProposalApiError(status, message);
}

/**
 * Adjusted values for confirming a label proposal (FTY-196). Every field is
 * optional: an empty object commits the parsed values unchanged. A supplied
 * `calories`/macro is a **value override** (commits the user's number, marks the
 * item edited); a supplied `amount` is the adjusted serving count applied as a
 * provenance-preserving rescale.
 */
export interface LabelProposalAdjustments {
  readonly calories?: number;
  readonly protein_g?: number;
  readonly carbs_g?: number;
  readonly fat_g?: number;
  readonly amount?: number;
}

/** Wire shape of the proposed-values read (`{ proposal: item | null }`). */
interface LabelProposalResponse {
  readonly proposal: DerivedFoodItemDTO | null;
}

/**
 * Read the uncounted proposed values for a label event (FTY-196). Returns the
 * parsed `DerivedFoodItemDTO` (with its `user_label` "Label scan" source) when the
 * event has an uncounted proposal, or `null` when it has none — an already
 * -confirmed, `needs_clarification`, `failed`, or non-label event are all an
 * absent proposal (no status oracle). A cross-user / nonexistent event is `404`.
 */
export async function getLabelProposal(
  session: ApiSession,
  eventId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<DerivedFoodItemDTO | null> {
  const data = await request<LabelProposalResponse>(
    userScopedUrl(
      session,
      `log-events/${encodeURIComponent(eventId)}/label-proposal`,
    ),
    {
      method: "GET",
      headers: authHeaders(session),
      action: "read the label parse",
      onError: labelProposalError,
      fetchImpl,
    },
  );
  return data.proposal ?? null;
}

/**
 * Confirm a label proposal so it counts toward the day's totals (FTY-196). Flips
 * the food item `proposed → resolved` in one transaction. Pass `adjustments` to
 * commit corrected values — only the fields the user changed should be sent so an
 * unchanged confirm keeps the parse un-edited (`is_edited: false`). A double
 * confirm is idempotent (the already-resolved item is returned, never
 * double-counted). Returns the committed `DerivedFoodItemDTO` at status
 * `resolved`.
 */
export async function confirmLabelProposal(
  session: ApiSession,
  eventId: string,
  adjustments: LabelProposalAdjustments = {},
  fetchImpl: typeof fetch = fetch,
): Promise<DerivedFoodItemDTO> {
  return request<DerivedFoodItemDTO>(
    userScopedUrl(
      session,
      `log-events/${encodeURIComponent(eventId)}/label-proposal/confirm`,
    ),
    {
      method: "POST",
      headers: authHeaders(session),
      body: JSON.stringify(adjustments),
      action: "confirm the label parse",
      onError: labelProposalError,
      fetchImpl,
    },
  );
}
