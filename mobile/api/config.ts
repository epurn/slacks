/**
 * Resolves the backend API base URL for the mobile client.
 *
 * The base URL is non-secret configuration: a self-hosted deployment points the
 * app at its own backend. It is resolved in priority order:
 *
 *   1. the **persisted runtime connection** the user established on the connect
 *      screen (FTY-107) — the server they entered or scanned and that the app
 *      probed for reachability, and
 *   2. the build-time Expo `extra.apiBaseUrl` (set per build/environment), and
 *   3. the local dev backend, so the app runs against `docker-compose` out of
 *      the box.
 *
 * The persisted connection is held in an in-memory cache so `resolveApiBaseUrl()`
 * stays **synchronous** — every existing API client keeps calling it unchanged.
 * The cache is hydrated on launch from the on-device connection store by the
 * `ConnectionProvider` (`state/connection.tsx`), which calls
 * {@link setConnectedBaseUrl} whenever the connection is established, changed, or
 * cleared. No tokens or secrets are resolved here — those come from the
 * authenticated session at call time, and the server URL is non-secret config.
 */

import Constants from "expo-constants";

/** Local FastAPI dev backend (see `docker-compose.yml`). */
export const DEFAULT_API_BASE_URL = "http://localhost:8000";

/**
 * The persisted runtime connection, mirrored in memory so the accessor stays
 * synchronous. `null` means no connection is established and the build-time
 * default is used. Driven by `ConnectionProvider` via {@link setConnectedBaseUrl}.
 */
let connectedBaseUrl: string | null = null;

/** Strip a trailing slash run, mirroring the historical normalization. */
function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

/**
 * Set (or clear) the persisted runtime connection that `resolveApiBaseUrl()`
 * prefers. Pass `null` to fall back to the build-time default. The value is
 * normalized (trimmed, trailing slash stripped) so the accessor always returns a
 * canonical base URL. Called by the connection store/provider — not by API
 * clients.
 */
export function setConnectedBaseUrl(url: string | null): void {
  if (url === null) {
    connectedBaseUrl = null;
    return;
  }
  const normalized = stripTrailingSlash(url.trim());
  connectedBaseUrl = normalized === "" ? null : normalized;
}

/**
 * The base URL the app falls back to when no runtime connection is established:
 * the build-time Expo `extra.apiBaseUrl`, or the local dev backend. This is the
 * "default server address" the Settings server editor (FTY-405) offers as the
 * way back from a custom address, so it is exported rather than inlined.
 */
export function defaultApiBaseUrl(): string {
  const extra = Constants.expoConfig?.extra as
    | { apiBaseUrl?: unknown }
    | undefined;
  const configured =
    typeof extra?.apiBaseUrl === "string" && extra.apiBaseUrl.trim() !== ""
      ? extra.apiBaseUrl.trim()
      : DEFAULT_API_BASE_URL;
  return stripTrailingSlash(configured);
}

/**
 * Return the configured API base URL without a trailing slash, preferring the
 * persisted runtime connection over the build-time default.
 */
export function resolveApiBaseUrl(): string {
  if (connectedBaseUrl !== null) {
    return connectedBaseUrl;
  }
  return defaultApiBaseUrl();
}
