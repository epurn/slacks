/**
 * E2E launch mode — deterministic dev-build harness (FTY-160).
 *
 * When active, this module:
 *   1. Seeds a synthetic authenticated session so the app boots past sign-in
 *      with no live auth dependency.
 *   2. Installs a global fetch mock so all API calls return hermetic fixtures
 *      with no live backend or network timing.
 *   3. Marks onboarding complete for the E2E user so the onboarding wizard
 *      never appears (the fixture profile already satisfies the check, but
 *      the module-level flag skips the async check altogether).
 *
 * SECURITY: This module is an auth bypass and a mock-API switch. It is
 * hard-gated by `__DEV__` (a React Native compile-time constant that Metro
 * sets to `false` in release/production builds, dead-code-eliminating this
 * entire branch). The `EXPO_PUBLIC_FATTY_E2E` env var provides a second gate
 * so only an explicitly built E2E debug binary can enter this mode.
 *
 * The mode is off by default and cannot be entered in a release build:
 *   - `__DEV__` is always `false` in release builds → isE2EMode() always false.
 *   - The env var is set only by `verify-e2e.sh` at build time, never by default.
 *   - `setupE2EMode()` and `installE2EMockFetch()` are no-ops when isE2EMode()
 *     returns false.
 */

import { markOnboardingComplete } from '@/state/onboardingComplete';
import type { SessionStore } from '@/state/sessionStore';
import type { ServerConnectionStore } from '@/state/serverConnectionStore';
import {
  E2E_SESSION,
  E2E_SERVER_URL,
  E2E_FIXTURE_MAP,
} from './fixtures';

/**
 * True only in a DEV build that was compiled with EXPO_PUBLIC_FATTY_E2E=true.
 *
 * In release builds `__DEV__` is `false` (compile-time constant) so this
 * function always returns `false` and Metro dead-code-eliminates the branch.
 */
export function isE2EMode(): boolean {
  if (!__DEV__) return false;
  return process.env.EXPO_PUBLIC_FATTY_E2E === 'true';
}

/**
 * In-memory session store pre-seeded with the E2E synthetic session.
 * Injected into SessionProvider in place of the real SecureStore when E2E mode
 * is active. No data is written to the device keychain.
 */
export const e2eSessionStore: SessionStore = {
  async save() {},
  async load() {
    return E2E_SESSION;
  },
  async clear() {},
};

/**
 * In-memory connection store pre-seeded with the E2E server URL.
 * Injected into ConnectionProvider in place of the real file store when E2E
 * mode is active. No data is written to the device filesystem.
 */
export const e2eConnectionStore: ServerConnectionStore = {
  async load() {
    return E2E_SERVER_URL;
  },
  async save() {},
  async clear() {},
};

/**
 * Build the E2E mock fetch function. Matches URLs by the path suffix after the
 * user-scoped API base and returns fixture JSON; returns 404 for anything else.
 * All responses are synthetic — no network I/O occurs.
 */
export function createE2EMockFetch(): typeof fetch {
  return async (input: RequestInfo | URL): Promise<Response> => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : (input as Request).url;

    for (const [suffix, fixture] of Object.entries(E2E_FIXTURE_MAP)) {
      // Match the suffix at the end of the path component, allowing query params.
      const pathEnd = url.split('?')[0];
      if (pathEnd.endsWith(suffix)) {
        return new Response(JSON.stringify(fixture), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        });
      }
    }

    return new Response(
      JSON.stringify({ detail: 'E2E fixture not found for this URL' }),
      {
        status: 404,
        headers: { 'Content-Type': 'application/json' },
      },
    );
  };
}

/**
 * Replace the global `fetch` with the E2E mock. No-op when isE2EMode() is
 * false (release builds, normal dev builds without the flag).
 *
 * Must be called before any API call is made — in practice, called at the
 * module-load-time side effect in app/_layout.tsx.
 */
export function installE2EMockFetch(): void {
  if (!isE2EMode()) return;
  // globalThis.fetch is available in RN JS environments; cast because the
  // TypeScript lib declares it read-only but RN lets tests/harnesses override it.
  (globalThis as Record<string, unknown>)['fetch'] = createE2EMockFetch();
}

/**
 * One-shot E2E mode setup called at app startup (from app/_layout.tsx).
 * No-op when isE2EMode() is false.
 *
 *  - Installs the mock fetch so all API calls use fixture responses.
 *  - Marks onboarding complete for the E2E user so AuthGate skips the async
 *    profile/goals check and routes straight to Today.
 */
export function setupE2EMode(): void {
  if (!isE2EMode()) return;
  installE2EMockFetch();
  markOnboardingComplete(E2E_SESSION.userId);
}
