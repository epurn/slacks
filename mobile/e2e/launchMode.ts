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
 * entire branch). The `EXPO_PUBLIC_SLACKS_E2E` env var provides a second gate
 * so only an explicitly built E2E debug binary can enter this mode.
 *
 * The mode is off by default and cannot be entered in a release build:
 *   - `__DEV__` is always `false` in release builds → isE2EMode() always false.
 *   - The env var is set only by `verify-e2e.sh` at build time, never by default.
 *   - `setupE2EMode()` and `installE2EMockFetch()` are no-ops when isE2EMode()
 *     returns false.
 */

import { AccessibilityInfo, LogBox } from 'react-native';
import type { PermissionResponse } from 'expo';
import type { useCameraPermissions } from 'expo-camera';
import { markOnboardingComplete } from '@/state/onboardingComplete';
import type { SessionStore } from '@/state/sessionStore';
import type { ServerConnectionStore } from '@/state/serverConnectionStore';
import {
  E2E_SESSION,
  E2E_SERVER_URL,
  E2E_CAMERA_PERMISSION_GRANTED,
} from './fixtures';
import { isActiveVisualReviewPresetSignedOut } from './visualReview/session';
import { createE2EMockFetch } from './mockFetch';

// The E2E mock-fetch handler lives in its own module (FTY-395); re-exported
// here so every `@/e2e/launchMode` import site keeps resolving unchanged.
export { createE2EMockFetch } from './mockFetch';

/**
 * True only in a DEV build that was compiled with EXPO_PUBLIC_SLACKS_E2E=true.
 *
 * In release builds `__DEV__` is `false` (compile-time constant) so this
 * function always returns `false` and Metro dead-code-eliminates the branch.
 */
export function isE2EMode(): boolean {
  if (!__DEV__) return false;
  return process.env.EXPO_PUBLIC_SLACKS_E2E === 'true';
}

/**
 * True when the E2E harness should force Reduce Motion ON (FTY-181).
 *
 * The signature beats degrade to a simple fade / value-set (no spring) under
 * Reduce Motion. Maestro cannot toggle the OS `isReduceMotionEnabled` flag, so a
 * reduce-motion E2E build sets this second env var and the harness overrides the
 * accessibility read — the hermetic equivalent of the OS toggle — letting the
 * `reduce-motion.yaml` flow verify the beats still complete on their no-motion
 * branch. Gated behind `isE2EMode()` so it is dead code in release builds.
 */
export function isE2EReduceMotionMode(): boolean {
  if (!isE2EMode()) return false;
  return process.env.EXPO_PUBLIC_SLACKS_E2E_REDUCE_MOTION === 'true';
}

/**
 * In-memory session store pre-seeded with the E2E synthetic session.
 * Injected into SessionProvider in place of the real SecureStore when E2E mode
 * is active. No data is written to the device keychain.
 *
 * `load()` reflects the active visual-review preset (FTY-247): a preset that
 * requests the signed-out surface hydrates a `null` session, every other preset
 * (and the default, preset-free E2E boot) hydrates the synthetic one. The root
 * layout remounts the SessionProvider on each preset activation, so this makes
 * the signed-out state non-sticky — switching back to a signed-in preset
 * reseeds the session at runtime with no rebuild and no order dependence.
 */
export const e2eSessionStore: SessionStore = {
  async save() {},
  async load() {
    return isActiveVisualReviewPresetSignedOut() ? null : E2E_SESSION;
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
 * E2E camera-permission hook (FTY-194). Drop-in for expo-camera's
 * `useCameraPermissions`, returning an already-granted permission so the
 * barcode scanner renders its granted chrome — reticle, torch, and the
 * "Type it instead" fallback — without a device camera. `CameraCapture`
 * defaults to this hook when `isE2EMode()` is true, so the
 * `barcode-manual-entry.yaml` flow can drive the real scanner path on the
 * simulator. `request`/`get` resolve to the same granted response; nothing is
 * ever asked of the OS. Dead code in release builds (never reached off E2E).
 */
export const e2eCameraPermissionsHook: typeof useCameraPermissions = () => {
  const grant = async (): Promise<PermissionResponse> =>
    E2E_CAMERA_PERMISSION_GRANTED;
  return [E2E_CAMERA_PERMISSION_GRANTED, grant, grant];
};

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
 * Force Reduce Motion ON for the reduce-motion E2E build (FTY-181). No-op unless
 * isE2EReduceMotionMode() — so it never affects the default motion-on suite or a
 * release build. Overrides `AccessibilityInfo.isReduceMotionEnabled` to resolve
 * `true`, the read the signature beats (theme/motion.ts) branch on; this is the
 * hermetic equivalent of the OS accessibility toggle Maestro cannot flip.
 */
export function applyE2EReduceMotion(): void {
  if (!isE2EReduceMotionMode()) return;
  // The RN typings declare the static as read-only; the runtime object is a
  // plain singleton the harness may override, mirroring the fetch override above.
  (AccessibilityInfo as unknown as Record<string, unknown>)[
    'isReduceMotionEnabled'
  ] = () => Promise.resolve(true);
}

/**
 * One-shot E2E mode setup called at app startup (from app/_layout.tsx).
 * No-op when isE2EMode() is false.
 *
 *  - Installs the mock fetch so all API calls use fixture responses.
 *  - Marks onboarding complete for the E2E user so AuthGate skips the async
 *    profile/goals check and routes straight to Today.
 *  - Forces Reduce Motion on when the reduce-motion E2E build is active, so the
 *    signature beats take their no-motion branch for the reduce-motion flow.
 */
export function setupE2EMode(): void {
  if (!isE2EMode()) return;
  installE2EMockFetch();
  markOnboardingComplete(E2E_SESSION.userId);
  applyE2EReduceMotion();
  // Silence the dev-client LogBox: its toasts (e.g. an expo-notifications
  // entitlement warning) float over bottom-of-screen UI and pollute the
  // visual-review screenshot evidence. Dead in release (isE2EMode() is false).
  LogBox.ignoreAllLogs(true);
}
