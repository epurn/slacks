/**
 * Typed client for the FTY-020 profile read/write API.
 *
 * The request/response shapes here mirror the persistence contract
 * (`docs/contracts/identity-and-profile.md`): canonical units only, a bearer
 * token for the authenticated user, and object-level ownership enforced by the
 * `{userId}` path. The client is a thin, injectable wrapper over `fetch` so the
 * capture flow can be tested offline and a future sign-in flow can supply the
 * session.
 *
 * Privacy: sensitive body values are never logged here. Errors carry only the
 * HTTP status and the endpoint, not the request body.
 */

import type {
  MetabolicFormula,
  ProfileUpdatePayload,
  UnitsPreference,
} from "@/state/profile";

/** The FTY-020 `ProfileDTO` response shape. */
export interface ProfileDTO {
  readonly user_id: string;
  readonly height_m: number | null;
  readonly weight_kg: number | null;
  readonly birth_year: number | null;
  readonly metabolic_formula: MetabolicFormula | string;
  readonly units_preference: UnitsPreference;
  readonly timezone: string;
  readonly updated_at: string;
}

/** Authenticated session needed to address the owner's profile. */
export interface ProfileSession {
  readonly baseUrl: string;
  readonly token: string;
  readonly userId: string;
}

/** Raised when the profile API returns a non-2xx status. */
export class ProfileApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ProfileApiError";
    this.status = status;
  }
}

function profileUrl(session: ProfileSession): string {
  return `${session.baseUrl}/api/users/${encodeURIComponent(
    session.userId,
  )}/profile`;
}

function authHeaders(session: ProfileSession): Record<string, string> {
  return {
    Authorization: `Bearer ${session.token}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
}

async function readError(
  response: Response,
  action: string,
): Promise<ProfileApiError> {
  // Map the documented status codes to plain, nonjudgmental messages without
  // echoing any request data back into the error.
  const message =
    response.status === 401
      ? "Your session has expired. Sign in again to save your profile."
      : response.status === 404
        ? "We couldn't find your profile."
        : response.status === 422
          ? "Some details couldn't be saved. Check your entries and try again."
          : `Could not ${action} (status ${response.status}).`;
  return new ProfileApiError(response.status, message);
}

/** Fetch the authenticated user's profile. */
export async function getProfile(
  session: ProfileSession,
  fetchImpl: typeof fetch = fetch,
): Promise<ProfileDTO> {
  const response = await fetchImpl(profileUrl(session), {
    method: "GET",
    headers: authHeaders(session),
  });
  if (!response.ok) {
    throw await readError(response, "load your profile");
  }
  return (await response.json()) as ProfileDTO;
}

/**
 * Persist a canonical profile update for the authenticated user and return the
 * stored profile. The payload is already in canonical units (see
 * `validateProfileForm`); this client does not transform body values.
 */
export async function putProfile(
  session: ProfileSession,
  payload: ProfileUpdatePayload,
  fetchImpl: typeof fetch = fetch,
): Promise<ProfileDTO> {
  const response = await fetchImpl(profileUrl(session), {
    method: "PUT",
    headers: authHeaders(session),
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw await readError(response, "save your profile");
  }
  return (await response.json()) as ProfileDTO;
}
