/**
 * The authenticated-session seam.
 *
 * FTY-020 built the backend auth path (register/login → bearer token), but the
 * mobile sign-in flow that obtains and stores that token is a separate, later
 * story. Until it lands there is no signed-in user on the device, so this hook
 * returns `null`. The profile capture flow renders a clear "sign in to save"
 * state in that case and is otherwise fully wired: once the sign-in story
 * provides a `{ token, userId }`, persistence works with no change to the form.
 *
 * Tests inject a session directly into the API client, so this placeholder
 * never gates the covered logic.
 */

import type { ProfileSession } from "@/api/profile";

import { resolveApiBaseUrl } from "@/api/config";

/** The signed-in user's session, or `null` when no one is signed in. */
export type Session = Pick<ProfileSession, "token" | "userId"> | null;

/**
 * Resolve the current session. Returns `null` until the sign-in flow exists.
 * The API base URL is always available so the seam can be completed by simply
 * returning a real `{ token, userId }` here.
 */
export function useSession(): Session {
  return null;
}

/** Combine a session with the resolved base URL into a `ProfileSession`. */
export function toProfileSession(session: NonNullable<Session>): ProfileSession {
  return {
    baseUrl: resolveApiBaseUrl(),
    token: session.token,
    userId: session.userId,
  };
}
