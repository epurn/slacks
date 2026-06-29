/**
 * Signed-out routing decision for the self-host-first first run (FTY-091),
 * extended with onboarding routing (FTY-103).
 *
 * Fatty's launch gate is four-state, and there must be no reachable dead-end
 * (UX design §4d):
 *
 *   1. no server connected (FTY-107)        → the connect screen,
 *   2. server connected but signed out       → the sign-in / create-account
 *      screen (FTY-091),
 *   3. signed in, onboarding incomplete     → the onboarding flow (FTY-103),
 *   4. signed in, onboarding complete       → the app (Today).
 *
 * This is the single, pure decision the root layout's gate consumes, so the
 * four states route coherently from one place rather than via scattered
 * per-screen redirects. It is pure (no navigator) so it is unit-tested
 * directly. The gate calls it on every relevant state change and performs the
 * returned `router.replace`, or nothing when it returns `null`.
 */

import type { ConnectionStatus } from "@/state/connection";
import type { Session, SessionStatus } from "@/state/session";

/** A route the gate should `replace` to, or `null` to stay put. */
export type AuthRedirectTarget = "/connect" | "/signin" | "/onboarding" | "/";

/**
 * Onboarding status for the signed-in user.
 *
 * `checking`     — the gate is still determining whether onboarding is needed
 *                  (async API call in progress). Hold: do not redirect yet.
 * `undetermined` — the check ran but could not reach a verdict (a transient
 *                  network failure or a 5xx, as opposed to a definitive 404).
 *                  Hold exactly like `checking`: never route a possibly-onboarded
 *                  returning user into onboarding just because the server was
 *                  briefly unreachable.
 * `incomplete`   — the user has no complete profile or no active goal; route
 *                  to onboarding.
 * `complete`     — onboarding is done; proceed to Today.
 */
export type OnboardingStatus =
  | 'checking'
  | 'undetermined'
  | 'incomplete'
  | 'complete';

/**
 * Result of probing one onboarding data source (the profile, the target).
 *
 * `present` — the resource exists and is usable (profile complete; target found).
 * `absent`  — the resource is definitively not set up: a 404, or a profile that
 *             loaded but is incomplete. This is a real signal to onboard.
 * `unknown` — the probe could not determine presence: a transient network
 *             failure, a timeout, or a 5xx. Carries no signal either way.
 */
export type OnboardingProbe = 'present' | 'absent' | 'unknown';

/**
 * Classify the signed-in user's onboarding status from the two data-source
 * probes. Pure, so the error-vs-not-found distinction the gate depends on is
 * unit-testable without rendering or networking.
 *
 * The rule, in order:
 * - If either probe is `unknown` (transient failure), we cannot tell → hold as
 *   `undetermined` rather than risk routing a real, onboarded user into the
 *   wizard (which would overwrite their active goal on re-completion).
 * - Both probes resolved: `complete` only when the profile is present *and* the
 *   target is present; otherwise `incomplete` (a definitive 404/absence).
 */
export function resolveOnboardingStatus(
  profile: OnboardingProbe,
  target: OnboardingProbe,
): OnboardingStatus {
  if (profile === 'unknown' || target === 'unknown') {
    return 'undetermined';
  }
  return profile === 'present' && target === 'present'
    ? 'complete'
    : 'incomplete';
}

export interface AuthRouteInput {
  /** Whether the persisted connection has hydrated (FTY-107). */
  readonly connectionStatus: ConnectionStatus;
  /** The connected server base URL, or `null` when none is connected. */
  readonly connection: string | null;
  /** Whether the persisted session has hydrated (FTY-090). */
  readonly sessionStatus: SessionStatus;
  /** The signed-in session, or `null` when signed out. */
  readonly session: Session;
  /** Onboarding completion status for the signed-in user (FTY-103). */
  readonly onboardingStatus: OnboardingStatus;
  /** Whether the app is currently on the connect screen. */
  readonly atConnect: boolean;
  /** Whether the app is currently on the sign-in screen. */
  readonly atSignin: boolean;
  /** Whether the app is currently on the onboarding screen (FTY-103). */
  readonly atOnboarding: boolean;
}

/**
 * Decide where a launch/state-change should be redirected, or `null` to stay.
 *
 * Hydration is awaited on **both** seams first: redirecting on a not-yet-known
 * connection or session would flash the wrong screen for a returning user.
 *
 * - No server connected → the connect screen (unless already there).
 * - Server connected but signed out → the sign-in screen (unless already there).
 * - Signed in, onboarding status still being checked or undetermined → hold (null).
 * - Signed in, onboarding incomplete → onboarding screen.
 * - Signed in, onboarding complete + on sign-in or onboarding screen → Today.
 * - Signed in, onboarding complete + on any other screen → stay (null).
 *
 * The connect screen is deliberately *not* forced shut for a signed-in user,
 * so the "change server" affordance can open it intentionally.
 *
 * Loop safety: once the gate routes to `/onboarding`, the `atOnboarding` guard
 * returns null. After the user completes onboarding and the status updates to
 * `complete`, subsequent calls route away from onboarding to Today.
 */
export function resolveAuthRedirect(
  input: AuthRouteInput,
): AuthRedirectTarget | null {
  const {
    connectionStatus,
    connection,
    sessionStatus,
    session,
    onboardingStatus,
    atConnect,
    atSignin,
    atOnboarding,
  } = input;

  // Hold until both seams have hydrated to avoid a wrong-screen flash.
  if (connectionStatus !== "ready" || sessionStatus !== "ready") {
    return null;
  }

  // Self-host-first: no server connected → the connect screen.
  if (connection === null) {
    return atConnect ? null : "/connect";
  }

  // Server connected but signed out → sign in / create an account.
  if (session === null) {
    return atSignin ? null : "/signin";
  }

  // Signed in: wait until the onboarding check has resolved. `undetermined`
  // (a transient/5xx probe failure, not a definitive 404) holds the same way —
  // we never push a possibly-onboarded returning user into onboarding on a
  // blip; they stay where they are until the next check resolves.
  if (onboardingStatus === "checking" || onboardingStatus === "undetermined") {
    return null;
  }

  // Onboarding incomplete → route to the onboarding flow (unless already there).
  if (onboardingStatus === "incomplete") {
    return atOnboarding ? null : "/onboarding";
  }

  // Onboarding complete: push the user off any gated screen.
  if (atOnboarding || atSignin) {
    return "/";
  }

  return null;
}
