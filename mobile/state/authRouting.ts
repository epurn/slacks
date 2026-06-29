/**
 * Signed-out routing decision for the self-host-first first run (FTY-091).
 *
 * Fatty's launch gate is three-state, and there must be no reachable dead-end
 * (UX design §4d):
 *
 *   1. no server connected (FTY-107)        → the connect screen,
 *   2. server connected but signed out       → the sign-in / create-account
 *      screen (FTY-091),
 *   3. a valid persisted session (FTY-090)   → the app (Today; a first run
 *      passes through onboarding first, handed off after auth — FTY-103).
 *
 * This is the single, pure decision the root layout's gate consumes, so the
 * three signed-out states route coherently from one place rather than via
 * scattered per-screen redirects. It is pure (no navigator) so it is unit-tested
 * directly. The gate calls it on every relevant state change and performs the
 * returned `router.replace`, or nothing when it returns `null`.
 */

import type { ConnectionStatus } from "@/state/connection";
import type { Session, SessionStatus } from "@/state/session";

/** A route the gate should `replace` to, or `null` to stay put. */
export type AuthRedirectTarget = "/connect" | "/signin" | "/";

export interface AuthRouteInput {
  /** Whether the persisted connection has hydrated (FTY-107). */
  readonly connectionStatus: ConnectionStatus;
  /** The connected server base URL, or `null` when none is connected. */
  readonly connection: string | null;
  /** Whether the persisted session has hydrated (FTY-090). */
  readonly sessionStatus: SessionStatus;
  /** The signed-in session, or `null` when signed out. */
  readonly session: Session;
  /** Whether the app is currently on the connect screen. */
  readonly atConnect: boolean;
  /** Whether the app is currently on the sign-in screen. */
  readonly atSignin: boolean;
}

/**
 * Decide where a launch/state-change should be redirected, or `null` to stay.
 *
 * Hydration is awaited on **both** seams first: redirecting on a not-yet-known
 * connection or session would flash the wrong screen for a returning user.
 *
 * - No server connected → the connect screen (unless already there).
 * - Server connected but signed out → the sign-in screen (unless already there).
 * - Signed in but stranded on the sign-in screen → the app (Today). The connect
 *   screen is deliberately *not* forced shut for a signed-in user, so the
 *   "change server" affordance can open it intentionally.
 */
export function resolveAuthRedirect(
  input: AuthRouteInput,
): AuthRedirectTarget | null {
  const {
    connectionStatus,
    connection,
    sessionStatus,
    session,
    atConnect,
    atSignin,
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

  // Signed in but still on the sign-in screen (e.g. a stale deep link) → Today.
  if (atSignin) {
    return "/";
  }

  return null;
}
