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
 * the HTTP status, a fixed action label, and — for the re-resolve `422`s — the
 * backend's fixed-vocabulary machine code, mapped to per-flow copy (FTY-366).
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

/**
 * The acting user's own confident prior correction for this item's normalized
 * name, offered as a top-ranked "Your correction" match candidate (FTY-407,
 * consuming the FTY-411 `prior_corrections` surface).
 *
 * Unlike a guessed {@link SourceCandidate}, the facts are the corrected **total**
 * for the item's own portion (`basis === "as_logged"`), not a per-basis density —
 * so a preview shows the whole-portion kcal, never "per 100g". A macro the
 * correction never supplied is honestly `null` (unknown), never a fabricated `0`.
 * `rescaled` marks a value carried from a different-portion prior via per-gram
 * rescale. Picking one applies through the same `reResolveItem` path — its
 * `source_ref` (`prior_correction:<hash>`) is the re-derivable handle.
 */
export interface PriorCorrectionCandidate {
  /** Always `prior_correction` — drives the "Your correction" provenance. */
  readonly source_type: "prior_correction";
  /** Opaque `prior_correction:<hash>` reference the re-resolve operation accepts. */
  readonly source_ref: string;
  /** Display name for the corrected food entry. */
  readonly name: string;
  /** Always `as_logged` — the facts are the corrected total for the item's portion. */
  readonly basis: "as_logged";
  /** Corrected energy total for the item's portion (kcal). */
  readonly calories: number;
  /** Corrected protein total (g), or `null` when the correction never supplied it. */
  readonly protein_g: number | null;
  /** Corrected carbohydrate total (g), or `null` when never supplied. */
  readonly carbs_g: number | null;
  /** Corrected fat total (g), or `null` when never supplied. */
  readonly fat_g: number | null;
  /** True when the value was carried from a different-portion prior by per-gram rescale. */
  readonly rescaled: boolean;
}

/**
 * A candidate the correction sheet can apply via {@link reResolveItem} — either a
 * guessed source match or the user's own prior correction. Both carry the
 * `source_ref` handle re-resolve accepts; that is all the apply path needs.
 * `PriorCorrectionCandidate.source_type` is the literal `"prior_correction"`, so
 * a caller that ever needs to tell the two apart can narrow on that discriminant.
 */
export type PickableCandidate = SourceCandidate | PriorCorrectionCandidate;

/**
 * The correction sheet's "Change match" candidates: the guessed-source matches
 * (`candidates`, USDA today) and, ranked above them, the acting user's own
 * confident prior corrections for this item's normalized name
 * (`priorCorrections`, FTY-411). `priorCorrections` is empty when the user has no
 * matching history, so an item with none renders exactly as before (no regression).
 */
export interface SourceCandidates {
  readonly candidates: readonly SourceCandidate[];
  readonly priorCorrections: readonly PriorCorrectionCandidate[];
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
 * Fixed re-resolve messages for the route's documented application-level `422`
 * codes (`evidence-retrieval.md` → Item Re-match → Errors). The user enters no
 * value on a re-resolve, so — unlike the value-edit flows — none of these say
 * "check the value"; each names the follow-up that can actually succeed
 * (FTY-366). All copy is fixed: no candidate name, query, or nutrition value
 * ever appears in an error.
 */
const RE_RESOLVE_422_MESSAGES: Readonly<Record<string, string>> = {
  // The chosen reference isn't re-derivable server-side; picking another
  // candidate (or searching again) is the follow-up that can work.
  source_not_resolvable:
    "That match couldn't be applied. Pick a different match or search again.",
  // The new source can't cost the item's current quantity; the follow-up it
  // needs is how much the user had.
  needs_clarification:
    "That match needs to know how much you had. Update the amount, then try the match again.",
};

/** Plain, non-blaming residual for a re-resolve `422` with no known code. */
const RE_RESOLVE_422_FALLBACK = "That match couldn't be applied. Try again.";

function reResolveError(
  status: number,
  action: string,
  errorCode?: string,
): CorrectionsApiError {
  if (status === 422) {
    const known =
      errorCode !== undefined ? RE_RESOLVE_422_MESSAGES[errorCode] : undefined;
    return new CorrectionsApiError(status, known ?? RE_RESOLVE_422_FALLBACK);
  }
  return correctionsError(status, action);
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
): Promise<SourceCandidates> {
  const body = query ? JSON.stringify({ query }) : "{}";
  const data = await request<{
    candidates: SourceCandidate[];
    prior_corrections?: PriorCorrectionCandidate[];
  }>(
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
  // `prior_corrections` is a defaulted list server-side (FTY-411); an older
  // server that omits it degrades cleanly to "no prior corrections".
  return {
    candidates: data.candidates,
    priorCorrections: data.prior_corrections ?? [],
  };
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
      onError: reResolveError,
      fetchImpl,
    },
  );
}
