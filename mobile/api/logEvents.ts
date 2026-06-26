/**
 * Typed client for the FTY-030 log-event API.
 *
 * The request/response shapes here mirror the log-events contract
 * (`docs/contracts/log-events.md`): a bearer token for the authenticated user,
 * object-level ownership enforced by the `{userId}` path, and the event status
 * vocabulary the Today timeline renders. The client is a thin, injectable
 * wrapper over `fetch` so the timeline can be tested offline and a future
 * sign-in flow can supply the session.
 *
 * Privacy: `raw_text` is sensitive personal data. It is never logged here, and
 * errors carry only the HTTP status and the attempted action, never the request
 * body.
 */

/** The FTY-030 event status state machine vocabulary (full v1 set). */
export type LogEventStatus =
  | "pending"
  | "processing"
  | "completed"
  | "failed"
  | "needs_clarification";

/** The FTY-030 event DTO, returned by create, each list element, and get. */
export interface LogEventDTO {
  readonly id: string;
  readonly user_id: string;
  readonly raw_text: string;
  readonly status: LogEventStatus;
  readonly created_at: string;
  readonly updated_at: string;
}

/** Authenticated session needed to address the owner's events. */
export interface LogEventSession {
  readonly baseUrl: string;
  readonly token: string;
  readonly userId: string;
}

/** Raised when the log-event API returns a non-2xx status. */
export class LogEventApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "LogEventApiError";
    this.status = status;
  }
}

function logEventsUrl(session: LogEventSession, query?: string): string {
  const base = `${session.baseUrl}/api/users/${encodeURIComponent(
    session.userId,
  )}/log-events`;
  return query ? `${base}?${query}` : base;
}

function authHeaders(session: LogEventSession): Record<string, string> {
  return {
    Authorization: `Bearer ${session.token}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
}

async function readError(
  response: Response,
  action: string,
): Promise<LogEventApiError> {
  // Map the documented status codes to plain, nonjudgmental messages without
  // echoing any request data (the user's raw text) back into the error.
  const message =
    response.status === 401
      ? "Your session has expired. Sign in again to keep logging."
      : response.status === 404
        ? "We couldn't find your log."
        : response.status === 422
          ? "That entry couldn't be saved. Try rephrasing it."
          : `Could not ${action} (status ${response.status}).`;
  return new LogEventApiError(response.status, message);
}

/**
 * List the authenticated user's events for a day. `day` is an optional
 * `YYYY-MM-DD`; when omitted the backend defaults to the current day in the
 * user's profile timezone (per the contract). Returns events oldest-first.
 */
export async function listTodayLogEvents(
  session: LogEventSession,
  day?: string,
  fetchImpl: typeof fetch = fetch,
): Promise<readonly LogEventDTO[]> {
  const query = day ? `day=${encodeURIComponent(day)}` : undefined;
  const response = await fetchImpl(logEventsUrl(session, query), {
    method: "GET",
    headers: authHeaders(session),
  });
  if (!response.ok) {
    throw await readError(response, "load your day");
  }
  return (await response.json()) as LogEventDTO[];
}

/**
 * Create a `pending` log event from the user's natural-language input and
 * return the stored event. The caller is responsible for trimming; the backend
 * also trims and rejects empty/oversized input as the trust boundary.
 */
export async function createLogEvent(
  session: LogEventSession,
  rawText: string,
  fetchImpl: typeof fetch = fetch,
): Promise<LogEventDTO> {
  const response = await fetchImpl(logEventsUrl(session), {
    method: "POST",
    headers: authHeaders(session),
    body: JSON.stringify({ raw_text: rawText }),
  });
  if (!response.ok) {
    throw await readError(response, "save your entry");
  }
  return (await response.json()) as LogEventDTO;
}
