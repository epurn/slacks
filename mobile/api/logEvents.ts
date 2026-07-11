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
  requestNoContent,
  userScopedUrl,
} from "@/api/client";
import type { ApiSession } from "@/api/client";
import type { DerivedItem } from "@/api/derivedItems";

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
 * A Today-feed-shaped day-listing row (FTY-198): one log event plus the derived
 * food/exercise items the timeline renders beneath it. Item DTOs reuse the
 * shared correction/item read-model, so each carries its `source` provenance and
 * `is_edited` flag. `items` is `[]` for an event with no derived items yet
 * (pending, needs_clarification, failed, or completed-with-no-items).
 */
export interface LogEventEntryDTO {
  readonly event: LogEventDTO;
  readonly items: readonly DerivedItem[];
}

/**
 * A single clarification question Fatty needs answered (FTY-170). Each question
 * carries a stable `id` — the key an answer submission references — the specific
 * question `text`, and an `options` array of candidate quick-pick values the
 * clarify sheet renders as one-tap chips. `options` MAY be empty (deterministic
 * backend-raised questions carry none); the sheet then shows the free-text
 * affordance only. Options are display candidates, never an enum — free text is
 * always an allowed answer (see `docs/contracts/log-events.md`).
 */
interface ClarificationQuestionDTO {
  readonly id: string;
  readonly text: string;
  readonly options: readonly string[];
}

/**
 * Response body for the owner-scoped clarification read (FTY-152/170). Carries
 * the event's persisted, still-unanswered clarification questions ordered by
 * `position`; an event not in `needs_clarification` (or with no unanswered rows)
 * yields `{ questions: [] }` (there is no status oracle).
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
 * List the day's entries in the Today-feed shape (FTY-198): each event with its
 * derived food/exercise item rows. This is the item-forward read the timeline
 * uses to render a completed entry's resolved value rows (name · kcal · source)
 * — the plain `listTodayLogEvents` above carries only event envelopes, so it
 * cannot populate the item rows that a pending row resolves into (FTY-180).
 * Owner-scoped like every other day read; the `day` query mirrors the event
 * list.
 */
export async function listTodayLogEventEntries(
  session: LogEventSession,
  day?: string,
  fetchImpl: typeof fetch = fetch,
): Promise<readonly LogEventEntryDTO[]> {
  const query = day ? `day=${encodeURIComponent(day)}` : undefined;
  const base = userScopedUrl(session, "log-events", "by-date");
  const url = query ? `${base}?${query}` : base;
  return request<LogEventEntryDTO[]>(url, {
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
 * Soft-void (delete) a log event (FTY-321): `DELETE .../log-events/{eventId}`.
 * The user is removing a mislogged entry; the backend sets a terminal
 * `voided_at` marker so the event and its derived items drop out of every read
 * model and the day's totals, without hard-deleting any row (the append-only
 * audit/provenance stance holds — see `docs/contracts/log-events.md`).
 *
 * Returns `void`: the contract answers `204 No Content` on both the first void
 * and every idempotent repeat. The operation is owner-scoped — a cross-user or
 * unknown id fails closed as `404` (no existence oracle), surfaced here as the
 * shared "couldn't find your log" message. `eventId` is not sensitive, but the
 * error carries only the status and action, never any log content.
 */
export async function deleteLogEvent(
  session: LogEventSession,
  eventId: string,
  fetchImpl: typeof fetch = fetch,
): Promise<void> {
  return requestNoContent(userScopedUrl(session, "log-events", eventId), {
    method: "DELETE",
    headers: authHeaders(session),
    action: "delete your entry",
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

/**
 * Answer one clarification question on a `needs_clarification` event (FTY-170).
 * The `answer` — a tapped quick-pick option's value or free text — is applied as
 * a **structured detail to the same event**, which the backend re-estimates in
 * place. This is the first-class resolve that replaces the retired create-path
 * re-submission (FTY-149): it never mutates `raw_text`, never creates a second
 * event, and never appends the answer into the raw phrase (audit A3/A5).
 *
 * The response is the **same** event's DTO. A fresh answer returns it at
 * `status: "processing"` (`201`); an idempotent replay of an already-answered
 * question returns the event's current status (`200`). This client treats both
 * `2xx` responses identically and returns the event so the caller updates the
 * entry in place and polls to terminal.
 *
 * `answer` is untrusted user input and sensitive: it is sent in the body and
 * never logged. The caller trims it; the backend also trims and rejects an
 * empty/whitespace answer (`422`) as the trust boundary.
 */
export async function answerClarification(
  session: LogEventSession,
  eventId: string,
  questionId: string,
  answer: string,
  fetchImpl: typeof fetch = fetch,
): Promise<LogEventDTO> {
  return request<LogEventDTO>(
    userScopedUrl(session, "log-events", eventId, "clarification", "answers"),
    {
      method: "POST",
      headers: authHeaders(session),
      body: JSON.stringify({ question_id: questionId, answer }),
      action: "submit your answer",
      onError: logEventError,
      fetchImpl,
    },
  );
}
