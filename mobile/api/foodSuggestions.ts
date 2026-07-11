/**
 * Typed client for the FTY-340 contextual food-suggestions endpoint.
 *
 * `getFoodSuggestions` — `GET /api/food-suggestions?limit=…`: reads the signed-in
 * user's own small, time-aware ranked list of "what do I probably mean to log
 * right now?", derived only from their saved foods and completed food-log
 * history (`docs/contracts/food-suggestions.md`). It is a read-only,
 * owner-scoped call with no egress — the route is scoped by the bearer token, so
 * there is no client-supplied user id and the URL is *not* user-scoped.
 *
 * The mobile quick-add chip row (FTY-341) consumes this: list order is canonical
 * (the client never re-ranks), a `saved_food_id` marks the suggestions the client
 * may apply through the FTY-053 estimator-skip path, and the labels/phrases are
 * the user's own text — never logged here.
 */

import { ApiError, authHeaders, request } from "@/api/client";
import type { ApiSession } from "@/api/client";

/** Default `limit` the endpoint applies when none is sent (contract v1). */
export const DEFAULT_FOOD_SUGGESTIONS_LIMIT = 8;

/** One ranked quick-add suggestion (mirrors the FTY-340 response item). */
export interface FoodSuggestionDTO {
  /** Display label for the chip. */
  readonly label: string;
  /** Phrase the client prefills into the composer for this suggestion. */
  readonly submit_phrase: string;
  /**
   * Present when the suggestion maps to a saved food, so the subsequent submit
   * may route through the FTY-053 estimator-skip apply path. `null` for
   * history-only candidates, which take the normal estimator submit.
   */
  readonly saved_food_id: string | null;
  /** Raw ranking score (debug only); list order is canonical, not this value. */
  readonly score: number;
}

/** Bounded suggestions response: the ranked items and the applied limit. */
export interface FoodSuggestionsResponse {
  readonly items: readonly FoodSuggestionDTO[];
  readonly limit: number;
}

/** Raised when the food-suggestions API returns a non-2xx status. */
export class FoodSuggestionsApiError extends ApiError {
  constructor(status: number, message: string) {
    super(status, message);
    this.name = "FoodSuggestionsApiError";
  }
}

function foodSuggestionsError(
  status: number,
  action: string,
): FoodSuggestionsApiError {
  const message =
    status === 401
      ? "Your session has expired. Sign in again."
      : `Could not ${action} (status ${status}).`;
  return new FoodSuggestionsApiError(status, message);
}

/**
 * Read the caller's ranked quick-add suggestions. `limit` is optional; the
 * server clamps it to `1..20` and defaults to `8`. The endpoint is scoped to the
 * authenticated user by the bearer token, so no user id is sent.
 */
export async function getFoodSuggestions(
  session: ApiSession,
  limit: number = DEFAULT_FOOD_SUGGESTIONS_LIMIT,
  fetchImpl: typeof fetch = fetch,
): Promise<FoodSuggestionsResponse> {
  const url = `${session.baseUrl}/api/food-suggestions?limit=${encodeURIComponent(
    String(limit),
  )}`;
  return request<FoodSuggestionsResponse>(url, {
    method: "GET",
    headers: authHeaders(session),
    action: "load your suggestions",
    onError: foodSuggestionsError,
    fetchImpl,
  });
}
