/**
 * Resolves the backend API base URL for the mobile client.
 *
 * The base URL is non-secret configuration: a self-hosted deployment points the
 * app at its own backend. It is read from the Expo runtime `extra.apiBaseUrl`
 * (set per build/environment) and falls back to the local dev backend so the
 * app runs against `docker-compose` out of the box. No tokens or secrets are
 * resolved here — those come from the authenticated session at call time.
 */

import Constants from "expo-constants";

/** Local FastAPI dev backend (see `docker-compose.yml`). */
export const DEFAULT_API_BASE_URL = "http://localhost:8000";

/** Return the configured API base URL without a trailing slash. */
export function resolveApiBaseUrl(): string {
  const extra = Constants.expoConfig?.extra as
    | { apiBaseUrl?: unknown }
    | undefined;
  const configured =
    typeof extra?.apiBaseUrl === "string" && extra.apiBaseUrl.trim() !== ""
      ? extra.apiBaseUrl.trim()
      : DEFAULT_API_BASE_URL;
  return configured.replace(/\/+$/, "");
}
