/**
 * Typed client for FTY-093 source candidates (list alternatives) and re-resolve
 * operations consumed by the correction sheet (FTY-100).
 *
 * Two operations from the evidence-retrieval.md Item Re-match contract:
 *
 * - `listSourceCandidates` — `POST .../source-candidates`: returns alternative
 *   source matches for the item, optionally filtered by a corrected search query.
 *   The query is item-identity only and passes through the server's sanitize_query
 *   chokepoint (length-bounded, control-stripped) before any provider egress.
 * - `reResolveItem` — `POST .../re-resolve`: re-aims the item to a chosen
 *   candidate reference and returns the updated `DerivedFoodItemDTO` with new
 *   provenance + recomputed values. Never accepts caller-supplied nutrition values.
 *
 * Both operations are scoped to the authenticated caller: cross-user access fails
 * closed as 404. Nutrition values and phrases are never logged; errors carry only
 * HTTP status + action label.
 */

import {
  ApiError,
  authHeaders,
  request,
  userScopedUrl,
} from "@/api/client";
import type { ApiSession } from "@/api/client";
import type { DerivedFoodItemDTO } from "@/api/derivedItems";

/**
 * A single alternative source match surfaced by the list-candidates operation.
 * Facts are per-basis (always per_100g for v1 USDA candidates) so the sheet can
 * show a compact kcal preview without committing to a serving size.
 */
export interface SourceCandidate {
  /** Evidence hierarchy type (`trusted_nutrition_database`, etc.). */
  readonly source_type: string;
  /** Stable opaque reference — the handle the re-resolve operation accepts. */
  readonly source_ref: string;
  /** Display name for the candidate food entry. */
  readonly name: string;
  /** Basis the preview facts are expressed against (`per_100g`). */
  readonly basis: string;
  /** Energy per basis (kcal). */
  readonly calories: number;
  /** Protein per basis (g), 0 when unavailable. */
  readonly protein_g: number;
  /** Carbohydrate per basis (g), 0 when unavailable. */
  readonly carbs_g: number;
  /** Total fat per basis (g), 0 when unavailable. */
  readonly fat_g: number;
}

/** Raised when a corrections API call returns a non-2xx status. */
export class CorrectionsApiError extends ApiError {
  constructor(status: number, message: string) {
    super(status, message);
    this.name = "CorrectionsApiError";
  }
}

function correctionsError(
  status: number,
  action: string,
): CorrectionsApiError {
  const message =
    status === 401
      ? "Your session has expired. Sign in again to continue."
      : status === 404
        ? "We couldn't find that item."
        : status === 422
          ? "That correction couldn't be applied. Check the value and try again."
          : status === 503
            ? "Alternatives are temporarily unavailable. Try again in a moment."
            : `Could not ${action} (status ${status}).`;
  return new CorrectionsApiError(status, message);
}

/**
 * List alternative source candidates for the given food item (FTY-093). An
 * optional `query` override re-aims the search to a different food name — it is
 * item-identity only and sanitized server-side before any provider egress.
 *
 * A 503 response means the candidate source was transiently unavailable; the
 * caller should surface a retryable message. An empty candidate list means "no
 * matches found" — not that the source was down.
 */
export async function listSourceCandidates(
  session: ApiSession,
  itemId: string,
  query?: string,
  fetchImpl: typeof fetch = fetch,
): Promise<readonly SourceCandidate[]> {
  const body = query ? JSON.stringify({ query }) : "{}";
  const data = await request<{ candidates: SourceCandidate[] }>(
    userScopedUrl(
      session,
      `derived-items/food/${encodeURIComponent(itemId)}/source-candidates`,
    ),
    {
      method: "POST",
      headers: authHeaders(session),
      body,
      action: "list alternatives",
      onError: correctionsError,
      fetchImpl,
    },
  );
  return data.candidates;
}

/**
 * Re-resolve a food item to a chosen candidate reference (FTY-093). The server
 * re-derives the facts from its cache (no fresh network egress), recomputes at the
 * current portion, and rewrites provenance honestly to the new source.
 *
 * Returns the updated `DerivedFoodItemDTO` with new provenance + values. The
 * server rejects any attempt to supply nutrition values directly — only the
 * `source_ref` is accepted; all math stays server-side.
 */
export async function reResolveItem(
  session: ApiSession,
  itemId: string,
  sourceRef: string,
  fetchImpl: typeof fetch = fetch,
): Promise<DerivedFoodItemDTO> {
  return request<DerivedFoodItemDTO>(
    userScopedUrl(
      session,
      `derived-items/food/${encodeURIComponent(itemId)}/re-resolve`,
    ),
    {
      method: "POST",
      headers: authHeaders(session),
      body: JSON.stringify({ source_ref: sourceRef }),
      action: "apply that match",
      onError: correctionsError,
      fetchImpl,
    },
  );
}
