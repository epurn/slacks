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

import {
  ApiError,
  authHeaders,
  request,
  userScopedUrl,
} from "@/api/client";
import type { ApiSession } from "@/api/client";

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

/**
 * A single clarification question Fatty needs answered (FTY-152). v1 surfaces
 * the question `text` only — the estimator produces no quick-pick options today,
 * so the clarify sheet answers via free-text. The shape is forward-compatible:
 * an `options` array can be added additively if the estimator later generates one.
 */
export interface ClarificationQuestionDTO {
  readonly text: string;
}

/**
 * Response body for the owner-scoped clarification read (FTY-152). Carries the
 * event's persisted clarification questions ordered by `position`; an event with
 * no clarification rows yields `{ questions: [] }` (there is no status oracle).
 */
export interface ClarificationDTO {
  readonly questions: readonly ClarificationQuestionDTO[];
}

/** Authenticated session needed to address the owner's events. */
export type LogEventSession = ApiSession;

/** Raised when the log-event API returns a non-2xx status. */
export class LogEventApiError extends ApiError {
  constructor(status: number, message: string) {
    super(status, message);
    this.name = "LogEventApiError";
  }
}

function logEventError(status: number, action: string): LogEventApiError {
  // Map the documented status codes to plain, nonjudgmental messages without
  // echoing any request data (the user's raw text) back into the error.
  const message =
    status === 401
      ? "Your session has expired. Sign in again to keep logging."
      : status === 404
        ? "We couldn't find your log."
        : status === 422
          ? "That entry couldn't be saved. Try rephrasing it."
          : `Could not ${action} (status ${status}).`;
  return new LogEventApiError(status, message);
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
  const base = userScopedUrl(session, "log-events");
  const url = query ? `${base}?${query}` : base;
  return request<LogEventDTO[]>(url, {
    method: "GET",
    headers: authHeaders(session),
    action: "load your day",
    onError: logEventError,
    fetchImpl,
  });
}

/**
 * Create a `pending` log event from the user's natural-language input and
 * return the stored event. The caller is responsible for trimming; the backend
 * also trims and rejects empty/oversized input as the trust boundary.
 *
 * `idempotencyKey` is the FTY-096 first-write-wins token (contract v2): when
 * supplied, the create is safe to retry — a fresh key creates the event (`201`),
 * a replay of an already-accepted key returns the existing event (`200`) without
 * a duplicate. Both are `2xx`, so this client treats them identically and
 * returns the resulting event. The offline outbox (FTY-104) generates the key
 * once at capture time and reuses it on every retry, which is what makes a
 * reconnect drain dedup-safe. The key is an opaque write-only token: it is sent
 * in the body and never logged.
 */
export async function createLogEvent(
  session: LogEventSession,
  rawText: string,
  idempotencyKey?: string,
  fetchImpl: typeof fetch = fetch,
): Promise<LogEventDTO> {
  const body: { raw_text: string; idempotency_key?: string } = {
    raw_text: rawText,
  };
  if (idempotencyKey !== undefined) {
    body.idempotency_key = idempotencyKey;
  }
  return request<LogEventDTO>(userScopedUrl(session, "log-events"), {
    method: "POST",
    headers: authHeaders(session),
    body: JSON.stringify(body),
    action: "save your entry",
    onError: logEventError,
    fetchImpl,
  });
}

/**
 * Read the clarification questions Fatty persisted for a `needs_clarification`
 * event (FTY-152). The clarify sheet (FTY-153) fetches this lazily when it opens
 * so the Today list/poll stays lean. Owner-scoped and fail-closed server-side: a
 * cross-user or unknown `eventId` is a `404`; an event with no clarification rows
 * returns `{ questions: [] }`. Question text is sensitive and never logged.
 */
export async function getLogEventClarification(
  session: LogEventSession,
  eventId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<ClarificationDTO> {
  return request<ClarificationDTO>(
    userScopedUrl(session, "log-events", eventId, "clarification"),
    {
      method: "GET",
      headers: authHeaders(session),
      action: "load the question",
      onError: logEventError,
      fetchImpl,
    },
  );
}
