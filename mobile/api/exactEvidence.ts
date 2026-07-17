/**
 * Typed client for the exact-evidence proposal contract (FTY-306), consumed by
 * the correction sheet's `Make it exact` lever (mobile flow FTY-311–FTY-313).
 *
 * For a **low-trust or incomplete** food item (`model_prior`, a `user_text` item
 * with rough/unknown macros, or a `reference_source` estimate) the user supplies
 * **product evidence** — a typed or scanned barcode, or a nutrition-label photo —
 * and Slacks builds a **server-held proposal** it can preview and then explicitly
 * apply in place. Three owner-scoped operations back the flow, per
 * `docs/contracts/evidence-retrieval.md` (**Exact Evidence Upgrade — FTY-306**)
 * and `docs/contracts/food-resolution.md` (**Exact Evidence Upgrade Routing**):
 *
 * - `requestBarcodeExactEvidenceProposal` —
 *   `POST .../derived-items/food/{item_id}/exact-upgrade/barcode`: sends only the
 *   barcode string; the server runs the hardened Open Food Facts path and returns
 *   a typed proposal (no item mutation on propose).
 * - `uploadLabelExactEvidenceProposal` —
 *   `POST .../derived-items/food/{item_id}/exact-upgrade/label?save={bool}`:
 *   uploads the raw label image bytes through the **same** client-side size/type
 *   guard as normal label capture; the server validates the image as data and
 *   extracts it, returning a typed proposal.
 * - `applyExactEvidenceProposal` —
 *   `POST .../derived-items/food/{item_id}/exact-upgrade/apply`: sends **only** the
 *   opaque `proposal_ref` plus an optional amount and returns the updated
 *   `DerivedFoodItemDTO`. Calories/macros can never be smuggled through this
 *   client — apply accepts no nutrition facts.
 *
 * Security / privacy (`docs/security/data-retention.md`, this contract's
 * **Authorization / privacy**): barcode requests carry only the barcode and the
 * authenticated item path; the label upload reuses the discard-by-default `save`
 * flag; apply carries only the opaque ref and an optional amount. Every operation
 * fails closed server-side — a cross-user or unknown user/item id is `404` with no
 * existence oracle. Errors carry only the HTTP status and a fixed action label —
 * never image URIs/bytes, barcode values, nutrition values, OCR text, or provider
 * output, and nothing is logged.
 */

import {
  ApiError,
  authHeaders,
  notifyUnauthorized,
  request,
  userScopedUrl,
} from "@/api/client";
import type { ApiSession } from "@/api/client";
import type { DerivedFoodItemDTO, ItemSourceDTO } from "@/api/derivedItems";
// Share the existing label-capture read + guard rather than duplicating them, so
// the exact-upgrade label path enforces the same first-line size/type boundary
// and uses the same robust native file upload fixed in FTY-381.
import { openLocalImage, uploadImageBinary, type OpenLocalImage } from "@/api/labelCapture";

/** Which evidence kind produced the proposal (`docs/contracts/evidence-retrieval.md`). */
export type ExactEvidenceProposalKind = "barcode" | "label";

/**
 * Proposal quality:
 * - `exact` — the evidence resolved through its exact source (barcode →
 *   `product_database`, label → `user_label`);
 * - `fallback` — exact evidence failed but a lower-trust estimator source produced
 *   a better rough result (kept honestly rough, never presented as exact);
 * - `none` — neither exact evidence nor a fallback could be produced; a failure
 *   read, not an applyable object.
 */
export type ExactEvidenceProposalQuality = "exact" | "fallback" | "none";

/**
 * Preview projection of the would-be item (`docs/contracts/evidence-retrieval.md`,
 * **Proposal (read shape)**). This is a **read projection**, not the full
 * `DerivedFoodItemDTO`: previewing creates no correction row, no evidence rewrite,
 * and no mutation. It reuses `ItemSourceDTO` for the source descriptor the applied
 * item would carry; `applyExactEvidenceProposal` returns the full item.
 */
export interface ExactEvidenceProposalPreview {
  /** The read-model source descriptor the applied item would carry. */
  readonly source: ItemSourceDTO;
  readonly calories: number | null;
  readonly protein_g: number | null;
  readonly carbs_g: number | null;
  readonly fat_g: number | null;
  /** The item's current amount, preserved by default at preview time. */
  readonly amount: number | null;
  /** The proposal's serving label (display only), or null when it has none. */
  readonly serving_label: string | null;
}

/** Fields shared by every proposal outcome. */
interface ExactEvidenceProposalBase {
  /**
   * Opaque, server-generated reference to the server-held proposal — the only key
   * `apply` accepts, never nutrition facts. Scoped to the owning user + item.
   */
  readonly proposal_ref: string;
  readonly kind: ExactEvidenceProposalKind;
  /**
   * Whether the proposal's source can cost the item's **current** amount. When
   * `false`, apply requires an explicit amount from the user — the client should
   * ask for one from the preview rather than applying with a guessed portion.
   */
  readonly can_cost_current_amount: boolean;
}

/** An exact proposal: resolved through its exact source, always applyable. */
export interface ExactEvidenceExactProposal extends ExactEvidenceProposalBase {
  readonly quality: "exact";
  readonly failure_reason: null;
  readonly preview: ExactEvidenceProposalPreview;
}

/**
 * A fallback proposal: exact evidence failed; an honestly-rough result is offered.
 * `failure_reason` is a closed, content-free label (e.g. `barcode_no_match`,
 * `label_unreadable`, `source_unavailable`) fixed server-side (FTY-307/FTY-308) —
 * never raw provider output, OCR text, fetched content, or image data. Typed as a
 * widened string so a new server label does not break the client.
 */
export interface ExactEvidenceFallbackProposal extends ExactEvidenceProposalBase {
  readonly quality: "fallback";
  readonly failure_reason: string;
  readonly preview: ExactEvidenceProposalPreview;
}

/**
 * A no-proposal failure read: nothing applyable, only a content-free
 * `failure_reason` for calm client copy (same closed vocabulary as a fallback).
 */
export interface ExactEvidenceNoneProposal extends ExactEvidenceProposalBase {
  readonly quality: "none";
  readonly failure_reason: string;
  readonly preview: null;
}

/**
 * A server-built exact-evidence proposal, discriminated by `quality`. A caller can
 * narrow on `quality` to tell an applyable `exact`/`fallback` proposal (non-null
 * `preview`) from a `none` failure read (null `preview`, required `failure_reason`).
 */
export type ExactEvidenceProposal =
  | ExactEvidenceExactProposal
  | ExactEvidenceFallbackProposal
  | ExactEvidenceNoneProposal;

/** Optional amount adjustment sent with apply; no nutrition facts are accepted. */
interface ApplyExactEvidenceBody {
  readonly proposal_ref: string;
  readonly amount?: number;
}

/** Raised when an exact-evidence API call returns a non-2xx status. */
export class ExactEvidenceApiError extends ApiError {
  constructor(status: number, message: string) {
    super(status, message);
    this.name = "ExactEvidenceApiError";
  }
}

/**
 * Raised client-side when a barcode is empty after trimming — the one client-side
 * barcode check allowed by the story (basic trim/non-empty). Shape (GTIN length,
 * check digit) validation stays server-authoritative and surfaces as a proposal
 * `failure_reason`, not an error.
 */
export class ExactEvidenceEmptyBarcodeError extends Error {
  constructor() {
    super("Enter a barcode to look up.");
    this.name = "ExactEvidenceEmptyBarcodeError";
  }
}

/**
 * Map documented statuses to plain, content-free copy for the correction sheet.
 * Never echoes the barcode, image, OCR text, provider output, or any nutrition
 * value — only the HTTP status and the attempted action.
 */
function exactEvidenceError(status: number, action: string): ExactEvidenceApiError {
  const message =
    status === 401
      ? "Your session has expired. Sign in again to keep logging."
      : status === 404
        ? "We couldn’t find that item."
        : status === 413
          ? "That photo is too large to upload."
          : status === 422
            ? "We couldn’t make that exact. Check the details and try again."
            : status === 503
              ? "That’s temporarily unavailable. Please try again in a moment."
              : `Could not ${action} (status ${status}).`;
  return new ExactEvidenceApiError(status, message);
}

/**
 * Request a **barcode** exact-evidence proposal for an eligible food item
 * (FTY-306). Sends only the trimmed barcode string and the auth headers to the
 * item-scoped barcode endpoint; the server runs the hardened Open Food Facts
 * lookup and returns a typed proposal (no item mutation). An empty barcode is
 * rejected client-side before any network call; all other barcode-shape checks
 * stay server-authoritative (an invalid shape returns a `none`/`fallback`
 * proposal, not an error). A cross-user / unknown item is `404`.
 */
export async function requestBarcodeExactEvidenceProposal(
  session: ApiSession,
  itemId: string,
  barcode: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ExactEvidenceProposal> {
  const trimmed = barcode.trim();
  if (trimmed.length === 0) {
    throw new ExactEvidenceEmptyBarcodeError();
  }
  return request<ExactEvidenceProposal>(
    userScopedUrl(
      session,
      `derived-items/food/${encodeURIComponent(itemId)}/exact-upgrade/barcode`,
    ),
    {
      method: "POST",
      headers: authHeaders(session),
      // Only the barcode — no other candidate fields, no nutrition facts, no text.
      body: JSON.stringify({ barcode: trimmed }),
      action: "look up that barcode",
      onError: exactEvidenceError,
      fetchImpl,
    },
  );
}

/**
 * Upload a captured nutrition-label photo as a **label** exact-evidence proposal
 * (FTY-306). Reads the local image, runs the **shared** label-capture size/type
 * guard before any network call, then POSTs the raw image bytes to the item-scoped
 * label endpoint with the declared `Content-Type` and the FTY-077 `save` retention
 * flag. The server validates the image as data and extracts it, returning a typed
 * proposal. Clears the session on a `401` (like `uploadLabelImage`), and never
 * includes the image URI, bytes, or extracted content in errors.
 */
export async function uploadLabelExactEvidenceProposal(
  session: ApiSession,
  itemId: string,
  imageUri: string,
  savePhoto: boolean,
  openImage: OpenLocalImage = openLocalImage,
): Promise<ExactEvidenceProposal> {
  const url =
    userScopedUrl(
      session,
      `derived-items/food/${encodeURIComponent(itemId)}/exact-upgrade/label`,
    ) + `?save=${savePhoto ? "true" : "false"}`;

  // Shared native read + guard + upload (FTY-381): reads the local image, runs
  // the size/type guard first, then streams the raw bytes from disk — never the
  // fragile `fetch(file://).blob()` path that failed before the POST.
  const { status, body } = await uploadImageBinary(
    url,
    session.token,
    imageUri,
    openImage,
  );

  if (status < 200 || status >= 300) {
    // This raw-body path bypasses request(), so it must clear the session on a
    // 401 itself, before throwing, so the caller's catch/finally still runs.
    if (status === 401) {
      notifyUnauthorized();
    }
    throw exactEvidenceError(status, "read that label");
  }

  return JSON.parse(body) as ExactEvidenceProposal;
}

/**
 * Apply a previewed proposal to the existing food item in place (FTY-306). Sends
 * **only** the opaque `proposal_ref` and an optional amount adjustment — never
 * calories/macros — so the client cannot inject nutrition facts; the server
 * re-derives the facts from the server-held proposal, rewrites provenance, and
 * returns the updated `DerivedFoodItemDTO`. Omit `amount` to keep the item's
 * current portion; supply it (e.g. when the preview reports
 * `can_cost_current_amount: false`) to cost the new source at that amount. A
 * cross-user / unknown item is `404`; an unresolvable ref or an uncostable amount
 * is `422`.
 */
export async function applyExactEvidenceProposal(
  session: ApiSession,
  itemId: string,
  proposalRef: string,
  amount?: number,
  fetchImpl: typeof fetch = fetch,
): Promise<DerivedFoodItemDTO> {
  const body: ApplyExactEvidenceBody =
    amount === undefined
      ? { proposal_ref: proposalRef }
      : { proposal_ref: proposalRef, amount };
  return request<DerivedFoodItemDTO>(
    userScopedUrl(
      session,
      `derived-items/food/${encodeURIComponent(itemId)}/exact-upgrade/apply`,
    ),
    {
      method: "POST",
      headers: authHeaders(session),
      body: JSON.stringify(body),
      action: "apply that exact match",
      onError: exactEvidenceError,
      fetchImpl,
    },
  );
}
