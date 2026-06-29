/**
 * Typed client for the FTY-020 local email + password auth path
 * (`docs/contracts/identity-and-profile.md`).
 *
 * Fatty is self-host-first with no hosted instance (UX design §4d), so an auth
 * call is always made against the user's *own* server: every call takes the
 * bound server base URL as an explicit argument and returns a normalized
 * session `{ serverUrl, token, userId }` that ties the issued token to the
 * server that minted it. A token from one self-hosted server is meaningless
 * against another, so the two never travel apart.
 *
 * Style mirrors `api/profile.ts`: a thin, injectable wrapper over `fetch` whose
 * errors carry only the HTTP status and the attempted action — never the email,
 * password, token, or response body. Auth failures map to plain,
 * **non-enumerating** messages: an unknown email and a wrong password return the
 * identical `401` text, so the UI boundary preserves the backend's
 * no-account-existence-oracle property.
 */

import type { SessionRecord } from "@/state/session";

/** Raised when an auth call returns a non-2xx status (or a malformed body). */
export class AuthApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "AuthApiError";
    this.status = status;
  }
}

/** `POST /api/auth/register` success body (FTY-020). */
interface RegisterResponse {
  readonly user?: { readonly id?: unknown };
  readonly token?: { readonly access_token?: unknown };
}

/** `POST /api/auth/login` success body (FTY-020) — note: no user id is returned. */
interface LoginResponse {
  readonly access_token?: unknown;
}

/**
 * Canonicalize a supplied server URL exactly as `resolveApiBaseUrl()` does
 * (trim, strip trailing slashes) so the bound URL is stored and addressed in a
 * single canonical form. Deep format/reachability validation (scheme, QR scan)
 * is FTY-091's connect screen, not this client.
 */
export function normalizeServerUrl(serverUrl: string): string {
  return serverUrl.trim().replace(/\/+$/, "");
}

/**
 * Map an auth status to a plain, non-enumerating message. `401` is identical
 * for an unknown email and a wrong password, so no message reveals whether an
 * account exists. `409` is only reachable on the register path.
 */
function authError(status: number, action: string): AuthApiError {
  const message =
    status === 401
      ? "That email or password didn't match. Check them and try again."
      : status === 409
        ? "An account already exists for this email. Try signing in instead."
        : status === 422
          ? "Enter a valid email and a password of at least 8 characters."
          : status === 429
            ? "Too many attempts. Wait a moment and try again."
            : `Could not ${action}. Please try again.`;
  return new AuthApiError(status, message);
}

/** A generic, body-free failure for a 2xx response whose shape is unusable. */
function malformedResponse(action: string): AuthApiError {
  return new AuthApiError(0, `Could not ${action}. Please try again.`);
}

function authHeaders(): Record<string, string> {
  return {
    "Content-Type": "application/json",
    Accept: "application/json",
  };
}

/**
 * Decode a base64url segment to a string. The token payload is ASCII JSON
 * (`sub` is a UUID, `iat`/`exp` are numbers), so a straight base64 decode is
 * sufficient. `globalThis.atob` is present in both Hermes (RN ≥ 0.74) and the
 * Node/Jest test runtime; if it is somehow absent we fail closed.
 */
function decodeBase64Url(segment: string): string {
  const decode = (globalThis as unknown as { atob?: (data: string) => string })
    .atob;
  if (typeof decode !== "function") {
    throw malformedResponse("sign in");
  }
  const normalized = segment.replace(/-/g, "+").replace(/_/g, "/");
  const remainder = normalized.length % 4;
  const padded =
    remainder === 0 ? normalized : normalized + "=".repeat(4 - remainder);
  return decode(padded);
}

/**
 * Derive the user id from the bearer token's `sub` claim, **for addressing
 * only**. The token is `<payload_b64url>.<signature_b64url>` where the payload
 * is `{ "sub": <user id>, "iat", "exp" }`. The signature is never verified and
 * no claim is trusted for an authorization decision client-side — the server
 * re-validates the token on every request and fails closed; `sub` is used
 * purely to build the owner-scoped profile URL.
 */
export function userIdFromToken(token: string): string {
  const parts = token.split(".");
  if (parts.length !== 2 || parts[0] === "") {
    throw malformedResponse("sign in");
  }
  let sub: unknown;
  try {
    const payload = JSON.parse(decodeBase64Url(parts[0])) as {
      sub?: unknown;
    };
    sub = payload.sub;
  } catch {
    throw malformedResponse("sign in");
  }
  if (typeof sub !== "string" || sub === "") {
    throw malformedResponse("sign in");
  }
  return sub;
}

/**
 * Create an account on the bound server and return a normalized session. Reads
 * the user id from the response `user.id` and the token from
 * `token.access_token`.
 */
export async function createAccount(
  serverUrl: string,
  email: string,
  password: string,
  fetchImpl: typeof fetch = fetch,
): Promise<SessionRecord> {
  const base = normalizeServerUrl(serverUrl);
  const response = await fetchImpl(`${base}/api/auth/register`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    throw authError(response.status, "create your account");
  }
  const data = (await response.json()) as RegisterResponse;
  const userId = data.user?.id;
  const token = data.token?.access_token;
  if (
    typeof userId !== "string" ||
    userId === "" ||
    typeof token !== "string" ||
    token === ""
  ) {
    throw malformedResponse("create your account");
  }
  return { serverUrl: base, token, userId };
}

/**
 * Sign in on the bound server and return a normalized session. Login returns
 * only the token, so the user id is derived from the token's `sub` claim.
 */
export async function signIn(
  serverUrl: string,
  email: string,
  password: string,
  fetchImpl: typeof fetch = fetch,
): Promise<SessionRecord> {
  const base = normalizeServerUrl(serverUrl);
  const response = await fetchImpl(`${base}/api/auth/login`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify({ email, password }),
  });
  if (!response.ok) {
    throw authError(response.status, "sign in");
  }
  const data = (await response.json()) as LoginResponse;
  const token = data.access_token;
  if (typeof token !== "string" || token === "") {
    throw malformedResponse("sign in");
  }
  return { serverUrl: base, token, userId: userIdFromToken(token) };
}
