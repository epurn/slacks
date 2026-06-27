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

/** The daily-summary DTO: intake, target, and exercise burn separated. */
export interface DailySummaryDTO {
  readonly date: string;
  readonly intake: {
    readonly calories: number;
    readonly protein_g: number;
    readonly carbs_g: number;
    readonly fat_g: number;
  };
  readonly target: {
    readonly calories: number;
  } | null;
  readonly exercise: {
    readonly active_calories: number;
  };
}

/** Authenticated session needed to fetch the user's daily summary. */
export interface DailySummarySession {
  readonly baseUrl: string;
  readonly token: string;
  readonly userId: string;
}

/** Raised when the daily-summary API returns a non-2xx status. */
export class DailySummaryApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "DailySummaryApiError";
    this.status = status;
  }
}

function dailySummaryUrl(
  session: DailySummarySession,
  query?: string,
): string {
  const base = `${session.baseUrl}/api/users/${encodeURIComponent(
    session.userId,
  )}/daily-summary`;
  return query ? `${base}?${query}` : base;
}

function authHeaders(session: DailySummarySession): Record<string, string> {
  return {
    Authorization: `Bearer ${session.token}`,
    Accept: "application/json",
  };
}

async function readError(
  response: Response,
  action: string,
): Promise<DailySummaryApiError> {
  const message =
    response.status === 401
      ? "Your session has expired. Sign in again to see your summary."
      : response.status === 404
        ? "We couldn't find your summary."
        : response.status === 422
          ? "Invalid date format."
          : `Could not ${action} (status ${response.status}).`;
  return new DailySummaryApiError(response.status, message);
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
  const response = await fetchImpl(dailySummaryUrl(session, query), {
    method: "GET",
    headers: authHeaders(session),
  });
  if (!response.ok) {
    throw await readError(response, "load your summary");
  }
  return (await response.json()) as DailySummaryDTO;
}
