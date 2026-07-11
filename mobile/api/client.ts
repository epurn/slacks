/**
 * Shared API client primitives for the mobile api/ layer.
 *
 * All authenticated, user-scoped JSON clients import from here instead of each
 * maintaining their own copies of the auth-header builder, URL helper, error
 * base, and fetch wrapper.
 *
 * Two special cases share only `ApiError`:
 *  - `auth.ts`: pre-session (no Bearer header)
 *  - `labelCapture.ts`: multipart upload (no JSON Content-Type)
 */

import type { ApiSession } from "@/state/session";
export type { ApiSession };

/** Base class for all api/ client errors. Subclasses override `name`. */
export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/**
 * Handler invoked when an authenticated request receives a `401`, i.e. the
 * stored bearer token is no longer valid (TTL expiry, or the self-hosted server
 * rotated `FATTY_AUTH_SECRET` so every existing token fails signature checks).
 *
 * `SessionProvider` registers its `signOut` here on mount so a dead token clears
 * the session — the existing auth-redirect then routes the user back to sign-in
 * instead of trapping them on a screen that 401s forever. The default is a no-op
 * so `request()` never throws when nothing is registered (e.g. unit tests that
 * exercise it directly). Registration is a single module-level slot: the last
 * `setUnauthorizedHandler` wins, and `null` restores the no-op.
 *
 * Not wired for the pre-session auth path (`auth.ts`): a `401` there is a
 * bad-credentials response, not a session expiry, and there is no session to
 * clear.
 */
export type UnauthorizedHandler = () => void;

const noopUnauthorizedHandler: UnauthorizedHandler = () => {};

let unauthorizedHandler: UnauthorizedHandler = noopUnauthorizedHandler;

/**
 * Register the handler invoked on an authenticated `401`. Pass `null` to restore
 * the safe default no-op (used on `SessionProvider` unmount). The handler must
 * be idempotent: several in-flight requests can each `401` at once, so it may be
 * called repeatedly — `signOut()` clearing an already-clear session is harmless.
 */
export function setUnauthorizedHandler(
  handler: UnauthorizedHandler | null,
): void {
  unauthorizedHandler = handler ?? noopUnauthorizedHandler;
}

/**
 * Invoke the registered unauthorized handler. Called from the api layer on an
 * authenticated `401`, before the caller's `ApiError` is thrown. Never receives
 * or logs the token or response body (`security-baseline.md`).
 */
export function notifyUnauthorized(): void {
  unauthorizedHandler();
}

/**
 * Standard JSON auth-header set for authenticated, user-scoped endpoints.
 * Do not use in `auth.ts` (no Bearer) or `labelCapture.ts` (multipart).
 */
export function authHeaders(session: ApiSession): Record<string, string> {
  return {
    Authorization: `Bearer ${session.token}`,
    "Content-Type": "application/json",
    Accept: "application/json",
  };
}

/**
 * Build a user-scoped URL: `${baseUrl}/api/users/${encodeURIComponent(userId)}`
 * with optional path segments appended (joined by `/`).
 */
export function userScopedUrl(
  session: ApiSession,
  ...segments: string[]
): string {
  const base = `${session.baseUrl}/api/users/${encodeURIComponent(session.userId)}`;
  return segments.length > 0 ? `${base}/${segments.join("/")}` : base;
}

/**
 * Fetch wrapper for authenticated JSON endpoints.
 *
 * On a 2xx response parses and returns the body as `T`. On non-2xx throws the
 * error returned by `onError(status, action)` — callers supply this function so
 * per-endpoint message text is preserved exactly without being logged here.
 */
export async function request<T>(
  url: string,
  opts: {
    method: string;
    headers: Record<string, string>;
    body?: string;
    action: string;
    onError: (status: number, action: string) => ApiError;
    fetchImpl?: typeof fetch;
  },
): Promise<T> {
  const fetchFn = opts.fetchImpl ?? fetch;
  const init: RequestInit = { method: opts.method, headers: opts.headers };
  if (opts.body !== undefined) {
    init.body = opts.body;
  }
  const response = await fetchFn(url, init);
  if (!response.ok) {
    // An authenticated 401 means the stored token is dead: clear the session
    // (via the registered handler) so the auth-redirect routes back to sign-in,
    // then throw the caller's error unchanged so per-endpoint catch/finally runs.
    if (response.status === 401) {
      notifyUnauthorized();
    }
    throw opts.onError(response.status, opts.action);
  }
  return (await response.json()) as T;
}

/**
 * Fetch wrapper for authenticated endpoints that return **no body** on success
 * (a `204 No Content`, e.g. the FTY-321 soft-void `DELETE`). Same error mapping
 * and `401` handling as {@link request}, but the 2xx path never reads/parses the
 * body — a `204` carries none, so `response.json()` would throw. Resolves `void`.
 */
export async function requestNoContent(
  url: string,
  opts: {
    method: string;
    headers: Record<string, string>;
    body?: string;
    action: string;
    onError: (status: number, action: string) => ApiError;
    fetchImpl?: typeof fetch;
  },
): Promise<void> {
  const fetchFn = opts.fetchImpl ?? fetch;
  const init: RequestInit = { method: opts.method, headers: opts.headers };
  if (opts.body !== undefined) {
    init.body = opts.body;
  }
  const response = await fetchFn(url, init);
  if (!response.ok) {
    if (response.status === 401) {
      notifyUnauthorized();
    }
    throw opts.onError(response.status, opts.action);
  }
  // 2xx with no content to parse (the delete contract returns 204).
}
