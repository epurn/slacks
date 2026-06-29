/**
 * Typed client for the FTY-051 derived-item edit API.
 *
 * The request/response shapes here mirror the corrections + edit contract
 * (`docs/contracts/corrections.md`): a single field override per `PATCH`, scoped
 * to the authenticated owner by the `{userId}` path, returning the updated
 * derived item carrying **both** the current values and the immutable
 * estimated/original snapshot. The UI is a thin consumer — the ratio rescale,
 * single-field override, and estimated-value preservation all live server-side;
 * a servings/quantity edit returns server-rescaled calories/macros that the UI
 * re-renders rather than computing (FTY-050).
 *
 * Privacy: item values (calories, macros, burn) are sensitive personal data.
 * They are never logged here, and errors carry only the HTTP status and the
 * attempted action — never the request body or any value.
 */

import {
  ApiError,
  authHeaders,
  request,
  userScopedUrl,
} from "@/api/client";
import type { ApiSession } from "@/api/client";

/** Resolution status of a derived item (mirrors the backend `DerivedItemStatus`). */
export type DerivedItemStatus = "unresolved" | "resolved";

/** Discriminator for the two derived-item kinds. */
export type DerivedItemType = "food" | "exercise";

/**
 * Per-item provenance source descriptor (FTY-092).
 * Derived server-side from the item's evidence_sources row; null when no
 * evidence record exists (defensive) and on exercise items.
 */
export interface ItemSourceDTO {
  /**
   * Evidence hierarchy type from evidence-retrieval.md.
   * `model_prior` signals the "≈ rough estimate · make it exact" treatment.
   */
  readonly source_type:
    | "trusted_nutrition_database"
    | "product_database"
    | "official_source"
    | "user_label"
    | "model_prior";
  /** Display-ready label (e.g. "USDA", "Open Food Facts", "Label scan", "Rough estimate"). */
  readonly label: string;
  /** Stable source reference (e.g. "usda_fdc:168880", "open_food_facts:barcode"). */
  readonly ref: string;
}

/**
 * Edit response for a food item: the editable current values plus the immutable
 * estimated/original snapshot the backend preserves. `amount` is the current
 * servings/quantity (driven by a `quantity` edit); there is no estimated
 * snapshot for it, since quantity is an input that drives the rescale, not a
 * snapshotted estimator output.
 *
 * FTY-092 adds `source` (provenance descriptor, server-derived) and `is_edited`
 * (true iff a direct value-override correction has been applied).
 */
export interface DerivedFoodItemDTO {
  readonly item_type: "food";
  readonly id: string;
  readonly user_id: string;
  readonly log_event_id: string;
  readonly name: string;
  readonly quantity_text: string;
  readonly unit: string | null;
  readonly amount: number | null;
  readonly status: DerivedItemStatus;
  readonly grams: number | null;
  readonly calories: number | null;
  readonly protein_g: number | null;
  readonly carbs_g: number | null;
  readonly fat_g: number | null;
  readonly calories_estimated: number | null;
  readonly protein_g_estimated: number | null;
  readonly carbs_g_estimated: number | null;
  readonly fat_g_estimated: number | null;
  readonly created_at: string;
  readonly updated_at: string;
  /** FTY-092 provenance descriptor; null when no evidence record exists (defensive). */
  readonly source?: ItemSourceDTO | null;
  /** FTY-092: true iff a direct value-override correction has been applied. */
  readonly is_edited?: boolean;
}

/** Edit response for an exercise item: current burn plus the original snapshot. */
export interface DerivedExerciseItemDTO {
  readonly item_type: "exercise";
  readonly id: string;
  readonly user_id: string;
  readonly log_event_id: string;
  readonly name: string;
  readonly quantity_text: string;
  readonly unit: string | null;
  readonly amount: number | null;
  readonly status: DerivedItemStatus;
  readonly active_calories: number | null;
  readonly active_calories_estimated: number | null;
  readonly created_at: string;
  readonly updated_at: string;
  /** FTY-092 provenance source; always null for exercise items (burn from MET tables). */
  readonly source?: null;
  /** FTY-092: true iff a direct value-override correction (burn override) has been applied. */
  readonly is_edited?: boolean;
}

/** A derived food or exercise item, discriminated by `item_type`. */
export type DerivedItem = DerivedFoodItemDTO | DerivedExerciseItemDTO;

/** Authenticated session needed to address the owner's derived items. */
export type DerivedItemSession = ApiSession;

/** Raised when the derived-item edit API returns a non-2xx status. */
export class DerivedItemApiError extends ApiError {
  constructor(status: number, message: string) {
    super(status, message);
    this.name = "DerivedItemApiError";
  }
}

function derivedItemError(
  status: number,
  action: string,
): DerivedItemApiError {
  // Map the documented status codes to plain, nonjudgmental messages. A 422 from
  // the edit endpoint carries a machine code (`unknown_field`, `out_of_range`,
  // …) but never echoes the value; the message here stays generic and never
  // reflects any value the user typed back at them.
  const message =
    status === 401
      ? "Your session has expired. Sign in again to keep editing."
      : status === 404
        ? "We couldn't find that item."
        : status === 422
          ? "That value couldn't be saved. Check it and try again."
          : `Could not ${action} (status ${status}).`;
  return new DerivedItemApiError(status, message);
}

/**
 * Edit one field of the owner's derived item (FTY-051). Sends a single
 * `field`/`value` override in canonical units (kcal, grams, or servings) and
 * returns the updated item — including any server-rescaled calories/macros when
 * the edited field is a food `quantity`. One `PATCH` per field is intentional and
 * matches the contract; the UI never batches fields.
 */
export async function editDerivedItem(
  session: DerivedItemSession,
  itemType: DerivedItemType,
  itemId: string,
  field: string,
  value: number,
  fetchImpl: typeof fetch = fetch,
): Promise<DerivedItem> {
  return request<DerivedItem>(
    userScopedUrl(
      session,
      `derived-items/${itemType}/${encodeURIComponent(itemId)}`,
    ),
    {
      method: "PATCH",
      headers: authHeaders(session),
      body: JSON.stringify({ field, value }),
      action: "save your correction",
      onError: derivedItemError,
      fetchImpl,
    },
  );
}
