/**
 * Typed client for the FTY-071 daily-summary API.
 *
 * The request/response shapes mirror the daily-summary contract
 * (`docs/contracts/daily-summary.md`): a bearer token for the authenticated user,
 * object-level ownership, and the separated figures (intake, macros, target,
 * exercise burn). The client is injectable for testing.
 *
 * Privacy: macros and burn figures are sensitive personal data. Errors carry
 * only the HTTP status and action, never the raw numbers.
 */

import {
  ApiError,
  authHeaders,
  request,
  userScopedUrl,
} from "@/api/client";
import type { ApiSession } from "@/api/client";

/** Provenance of a target value: derived by the calculator vs. set by the user. */
export type TargetSource = "derived" | "user";

/**
 * One target value (calorie or a macro) with explicit provenance (FTY-095).
 *
 * `effective` is the number the app uses (the override when set, else the
 * derived value); `derived` is the calculator value a reset restores; `source`
 * says which of the two `effective` came from. All whole numbers in canonical
 * units (kcal for calories, grams for macros).
 */
export interface TargetComponent {
  readonly effective: number;
  readonly derived: number;
  readonly source: TargetSource;
}

/**
 * The day's calorie + macro target read-model (FTY-094/FTY-095). Each component
 * carries its effective value, derived value, and `derived | user` provenance.
 */
export interface TargetReadModel {
  readonly calories: TargetComponent;
  readonly protein_g: TargetComponent;
  readonly carbs_g: TargetComponent;
  readonly fat_g: TargetComponent;
}

/** The daily-summary DTO: intake, target, and exercise burn separated. */
export interface DailySummaryDTO {
  readonly date: string;
  readonly intake: {
    readonly calories: number;
    readonly protein_g: number;
    readonly carbs_g: number;
    readonly fat_g: number;
  };
  /**
   * True iff the day has at least one finalized food item. `intake` is zeroed
   * both for an unlogged day and for a genuinely zero-kcal logged day, so the
   * zero alone can't tell them apart — this flag does. The Trends adherence
   * series excludes `has_intake: false` days from its logged-intake average and
   * on/off-target denominator instead of counting them as real 0-kcal days.
   */
  readonly has_intake: boolean;
  /**
   * Count of the day's entries that are **logged but not yet counted** toward
   * `intake` because they await a user action — the sum of the user's
   * `needs_clarification` log events and `proposed` (unconfirmed) items on the
   * day (FTY-223). `pending`/`processing` (still estimating) and `failed`
   * entries are excluded. Zero for a genuinely empty day, so it — not
   * `has_intake` alone — is what lets the Trends adherence card tell a day with
   * nothing logged apart from a day whose only entries are uncounted ("N entries
   * awaiting details"). See `docs/contracts/daily-summary.md`.
   */
  readonly uncounted_entries: number;
  readonly target: TargetReadModel | null;
  readonly exercise: {
    readonly active_calories: number;
  };
}

/** Authenticated session needed to fetch the user's daily summary. */
export type DailySummarySession = ApiSession;

/** Raised when the daily-summary API returns a non-2xx status. */
export class DailySummaryApiError extends ApiError {
  constructor(status: number, message: string) {
    super(status, message);
    this.name = "DailySummaryApiError";
  }
}

function dailySummaryError(
  status: number,
  action: string,
): DailySummaryApiError {
  const message =
    status === 401
      ? "Your session has expired. Sign in again to see your summary."
      : status === 404
        ? "We couldn't find your summary."
        : status === 422
          ? "Invalid date format."
          : `Could not ${action} (status ${status}).`;
  return new DailySummaryApiError(status, message);
}

/**
 * Fetch the authenticated user's daily summary: calories, macros, target, and
 * exercise burn for a specific day (or today if omitted). The figures are
 * separated, never netted. `day` is optional `YYYY-MM-DD`; when omitted the
 * backend defaults to the current day in the user's profile timezone.
 */
export async function getDailySummary(
  session: DailySummarySession,
  day?: string,
  fetchImpl: typeof fetch = fetch,
): Promise<DailySummaryDTO> {
  const query = day ? `day=${encodeURIComponent(day)}` : undefined;
  const base = userScopedUrl(session, "daily-summary");
  const url = query ? `${base}?${query}` : base;
  return request<DailySummaryDTO>(url, {
    method: "GET",
    headers: authHeaders(session),
    action: "load your summary",
    onError: dailySummaryError,
    fetchImpl,
  });
}

/**
 * Fetch the authenticated user's daily summaries for every day in `[from, to]`
 * (inclusive, `YYYY-MM-DD`, oldest-first) in a single request.
 *
 * This backs the Trends adherence series: one range read instead of one request
 * per day. Every calendar day in the range is returned — days without finalized
 * data carry zeroed intake/burn and a `null` target — so the client maps the
 * response straight onto the strip without fanning out.
 */
export async function getDailySummaryRange(
  session: DailySummarySession,
  from: string,
  to: string,
  fetchImpl: typeof fetch = fetch,
): Promise<DailySummaryDTO[]> {
  const query = `from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`;
  const url = `${userScopedUrl(session, "daily-summary/range")}?${query}`;
  return request<DailySummaryDTO[]>(url, {
    method: "GET",
    headers: authHeaders(session),
    action: "load your summary",
    onError: dailySummaryError,
    fetchImpl,
  });
}
