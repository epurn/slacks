/**
 * Module-level session flag for onboarding completion (FTY-103).
 *
 * Prevents the auth gate from re-routing a user back to onboarding immediately
 * after they complete it in the current JS process, before the async API
 * re-check has had time to reflect the newly-written profile + goal.
 *
 * The flag is keyed by userId so it resets automatically when a different
 * user signs in. It persists for the lifetime of the JS process (app session);
 * a fresh launch re-checks via the API (which is the source of truth for
 * returning users who completed onboarding in a previous session).
 */

let completedUserId: string | null = null;

/** Mark that the signed-in user has completed onboarding this session. */
export function markOnboardingComplete(userId: string): void {
  completedUserId = userId;
}

/** True iff this user completed onboarding in the current JS process. */
export function isOnboardingCompleteForUser(userId: string): boolean {
  return completedUserId === userId;
}

/** Reset when the session ends (sign-out). */
export function clearOnboardingComplete(): void {
  completedUserId = null;
}
