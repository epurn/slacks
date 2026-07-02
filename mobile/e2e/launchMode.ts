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
  E2E_DAILY_SUMMARY,
  E2E_CLARIFY_EVENT,
  E2E_CLARIFICATION,
  E2E_RESOLVED_EVENT,
  E2E_RESOLVED_SUMMARY,
  E2E_FAILED_RAW_TEXT,
  E2E_FAILED_EVENT,
  E2E_FAILED_RETRY_EVENT,
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
 * Build the E2E mock fetch function. Returns hermetic fixture JSON for every
 * API call the app makes — no network I/O. The mock is stateful: it tracks the
 * clarify-flow phase so the smoke flow (FTY-160) and the clarify flow (FTY-162)
 * can share one binary without conflicting fixture state.
 *
 * Phase transitions (driven by POST /log-events calls):
 *   phase 0 — empty day (smoke test; no POST made)
 *   phase 1 — needs_clarification entry visible (after first POST)
 *   phase 2 — entry resolved and counting (after second POST / re-submission)
 *
 * The smoke flow never POSTs, so it always sees the phase-0 empty-day fixture.
 *
 * The FTY-176 failed-parse flow runs off a separate `failedStage` keyed on the
 * gibberish `raw_text` (never "coffee"), so it drives independent state in the
 * same binary: stage 0 → first gibberish POST returns a `failed` event; stage 1
 * → a Retry POST returns a fresh `pending` attempt. GET reflects the stage so a
 * poll never drops the reconciled server row.
 */
export function createE2EMockFetch(): typeof fetch {
  let phase: 0 | 1 | 2 = 0;
  let failedStage: 0 | 1 | 2 = 0;

  const rawTextOf = (init?: RequestInit): string | undefined => {
    if (typeof init?.body !== 'string') return undefined;
    try {
      return (JSON.parse(init.body) as { raw_text?: string }).raw_text;
    } catch {
      return undefined;
    }
  };

  const json = (body: unknown, status = 200): Response =>
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });

  return async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url =
      typeof input === 'string'
        ? input
        : input instanceof URL
          ? input.href
          : (input as Request).url;

    const method = (
      init?.method ?? (input instanceof Request ? input.method : 'GET')
    ).toUpperCase();

    const pathEnd = url.split('?')[0];

    // /log-events — POST advances state and returns the next event;
    // GET returns the state-appropriate event list.
    if (pathEnd.endsWith('/log-events')) {
      if (method === 'POST') {
        // FTY-176 failed-parse flow: gibberish text fails first, then a Retry
        // produces a fresh pending attempt. Keyed on raw_text so it never
        // collides with the clarify flow's "coffee" phase machine.
        if (rawTextOf(init) === E2E_FAILED_RAW_TEXT) {
          if (failedStage === 0) {
            failedStage = 1;
            return json(E2E_FAILED_EVENT, 201);
          }
          failedStage = 2;
          return json(E2E_FAILED_RETRY_EVENT, 201);
        }
        if (phase === 0) {
          phase = 1;
          return json(E2E_CLARIFY_EVENT, 201);
        }
        phase = 2;
        return json(E2E_RESOLVED_EVENT, 201);
      }
      // The failed-parse flow's GET reflects its own stage so a poll never drops
      // the reconciled failed / retry-pending row.
      if (failedStage === 1) return json([E2E_FAILED_EVENT]);
      if (failedStage === 2) return json([E2E_FAILED_RETRY_EVENT]);
      if (phase === 0) return json([]);
      if (phase === 1) return json([E2E_CLARIFY_EVENT]);
      return json([E2E_RESOLVED_EVENT]);
    }

    // /clarification — the clarify sheet's lazy question-read.
    if (pathEnd.endsWith('/clarification')) {
      return json(E2E_CLARIFICATION);
    }

    // /daily-summary — returns non-zero intake once the entry is resolved.
    if (pathEnd.endsWith('/daily-summary')) {
      return json(phase === 2 ? E2E_RESOLVED_SUMMARY : E2E_DAILY_SUMMARY);
    }

    // Static fixtures (profile, target).
    for (const [suffix, fixture] of Object.entries(E2E_FIXTURE_MAP)) {
      if (pathEnd.endsWith(suffix)) {
        return json(fixture);
      }
    }

    return json({ detail: 'E2E fixture not found for this URL' }, 404);
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
