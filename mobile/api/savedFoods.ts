/**
 * Typed client for the FTY-052 saved-food save and typeahead search API.
 *
 * Two operations consumed by the mobile saved-food UI (FTY-053):
 *
 * - `saveFood` — `POST /api/users/{user_id}/saved-foods`: persists a corrected
 *   food from the editing surface (FTY-050), recording the typed phrase as an
 *   alias. The caller supplies the canonical name, the originating phrase, and
 *   the corrected nutrition snapshot.
 * - `searchSavedFoods` — `GET /api/users/{user_id}/saved-foods?q=…`: prefix-
 *   matched typeahead against the user's saved foods and their aliases,
 *   returning the matching foods with stored nutrition so the client can apply
 *   them directly.
 *
 * Both operations are scoped to the authenticated caller: cross-user access
 * fails closed as 404. The typed phrase and query text are never logged here;
 * errors carry only the HTTP status and the attempted action.
 */

/** Per-serving nutrition crossing the save boundary (mirrors FTY-052 backend). */
export interface NutritionSnapshot {
  readonly calories: number;
  readonly protein_g: number | null;
  readonly carbs_g: number | null;
  readonly fat_g: number | null;
  readonly serving_size: number;
  readonly serving_unit: string;
}

/** Request body for the deliberate save of a corrected food. */
export interface SaveFoodRequest {
  /** Canonical name to save under (also used as the display name). */
  readonly name: string;
  /** The typed phrase that originated this save, persisted as an alias. */
  readonly phrase: string;
  /** The corrected nutrition snapshot to store. */
  readonly nutrition: NutritionSnapshot;
}

/** A user-owned saved food returned on save and typeahead search. */
export interface SavedFoodDTO {
  readonly id: string;
  readonly user_id: string;
  readonly name: string;
  readonly calories: number;
  readonly protein_g: number | null;
  readonly carbs_g: number | null;
  readonly fat_g: number | null;
  readonly serving_size: number;
  readonly serving_unit: string;
  /** Provenance: always `'saved_from_correction'` in v1. */
  readonly source: string;
  readonly created_at: string;
  readonly updated_at: string;
}

/** Bounded typeahead response: matched saved foods and the applied limit. */
export interface SavedFoodSearchResponse {
  readonly items: readonly SavedFoodDTO[];
  readonly limit: number;
}

/** Authenticated session needed to address the owner's saved foods. */
export interface SavedFoodSession {
  readonly baseUrl: string;
  readonly token: string;
  readonly userId: string;
}

/** Raised when the saved-food API returns a non-2xx status. */
export class SavedFoodApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "SavedFoodApiError";
    this.status = status;
  }
}

function authHeaders(session: SavedFoodSession): Record<string, string> {
  return {
    Authorization: `Bearer ${session.token}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
}

function savedFoodsUrl(session: SavedFoodSession): string {
  return `${session.baseUrl}/api/users/${encodeURIComponent(session.userId)}/saved-foods`;
}

async function readError(
  response: Response,
  action: string,
): Promise<SavedFoodApiError> {
  const message =
    response.status === 401
      ? "Your session has expired. Sign in again to keep saving."
      : response.status === 404
        ? "We couldn't find that saved food."
        : response.status === 422
          ? "That food couldn't be saved. Check the values and try again."
          : `Could not ${action} (status ${response.status}).`;
  return new SavedFoodApiError(response.status, message);
}

/**
 * Save one corrected food for the caller, recording their typed phrase as an
 * alias. Returns the stored saved food carrying its nutrition snapshot.
 * Cross-user saves fail closed as 404.
 */
export async function saveFood(
  session: SavedFoodSession,
  request: SaveFoodRequest,
  fetchImpl: typeof fetch = fetch,
): Promise<SavedFoodDTO> {
  const response = await fetchImpl(savedFoodsUrl(session), {
    method: "POST",
    headers: authHeaders(session),
    body: JSON.stringify(request),
  });
  if (!response.ok) {
    throw await readError(response, "save your food");
  }
  return (await response.json()) as SavedFoodDTO;
}

/**
 * Search the caller's saved foods and aliases by normalized prefix/contains.
 * Each result carries its stored nutrition so the client can apply it directly
 * without re-estimating. Cross-user searches fail closed as 404.
 */
export async function searchSavedFoods(
  session: SavedFoodSession,
  query: string,
  fetchImpl: typeof fetch = fetch,
): Promise<SavedFoodSearchResponse> {
  const url = `${savedFoodsUrl(session)}?q=${encodeURIComponent(query)}`;
  const response = await fetchImpl(url, {
    method: "GET",
    headers: authHeaders(session),
  });
  if (!response.ok) {
    throw await readError(response, "search your saved foods");
  }
  return (await response.json()) as SavedFoodSearchResponse;
}
