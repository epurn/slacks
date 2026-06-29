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
    throw opts.onError(response.status, opts.action);
  }
  return (await response.json()) as T;
}
