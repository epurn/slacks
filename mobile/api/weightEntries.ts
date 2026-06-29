/**
 * Typed client for the FTY-070 weight-entry create and list-range API.
 *
 * The POST request body accepts `weight` in the user's `units_preference` (kg
 * for metric, lb for imperial); the backend converts to canonical kg on write.
 * All responses return `weight_kg` in canonical kilograms.
 *
 * Privacy: body weight is sensitive personal data. Errors carry only the HTTP
 * status and the attempted action — never the submitted weight value.
 */

import {
  ApiError,
  authHeaders,
  request,
  userScopedUrl,
} from "@/api/client";
import type { ApiSession } from "@/api/client";

export interface WeightEntryDTO {
  readonly id: string;
  readonly user_id: string;
  readonly weight_kg: number;
  readonly effective_date: string;
  readonly created_at: string;
  readonly updated_at: string;
}

/** Authenticated session needed to address the owner's weight entries. */
export type WeightSession = ApiSession;

/** Raised when the weight-entry API returns a non-2xx status. */
export class WeightApiError extends ApiError {
  constructor(status: number, message: string) {
    super(status, message);
    this.name = "WeightApiError";
  }
}

function weightError(status: number, action: string): WeightApiError {
  const message =
    status === 401
      ? "Your session has expired. Sign in again."
      : status === 404
        ? "We couldn't find your weight log."
        : status === 422
          ? "That entry couldn't be saved. Check the value and try again."
          : `Could not ${action} (status ${status}).`;
  return new WeightApiError(status, message);
}

/**
 * Create a weight entry. `weight` is in the user's `units_preference` (kg for
 * metric, lb for imperial) — the backend converts to canonical kg on write.
 * Returns the stored entry with `weight_kg` in canonical kilograms.
 */
export async function createWeightEntry(
  session: WeightSession,
  weight: number,
  effectiveDate: string,
  fetchImpl: typeof fetch = fetch,
): Promise<WeightEntryDTO> {
  return request<WeightEntryDTO>(userScopedUrl(session, "weight-entries"), {
    method: "POST",
    headers: authHeaders(session),
    body: JSON.stringify({ weight, effective_date: effectiveDate }),
    action: "save your weight",
    onError: weightError,
    fetchImpl,
  });
}

/**
 * List the authenticated user's weight entries over a date range.
 * Both bounds are optional (open-ended when omitted). When both are provided,
 * `from` must be on or before `to`.
 * Returns entries ordered oldest-first by `effective_date`.
 */
export async function listWeightEntries(
  session: WeightSession,
  from?: string,
  to?: string,
  fetchImpl: typeof fetch = fetch,
): Promise<readonly WeightEntryDTO[]> {
  const parts: string[] = [];
  if (from) parts.push(`from=${encodeURIComponent(from)}`);
  if (to) parts.push(`to=${encodeURIComponent(to)}`);
  const query = parts.length > 0 ? `?${parts.join("&")}` : "";
  const url = `${userScopedUrl(session, "weight-entries")}${query}`;
  return request<WeightEntryDTO[]>(url, {
    method: "GET",
    headers: authHeaders(session),
    action: "load your weight log",
    onError: weightError,
    fetchImpl,
  });
}
