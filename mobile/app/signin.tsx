/**
 * Sign-in / create-account route (`/signin`) — the auth step of the
 * self-host-first first run (FTY-091). Thin wrapper: the testable screen lives
 * in `SignInScreen`. The root layout's auth gate (`state/authRouting`) routes a
 * connected-but-signed-out launch here.
 *
 * Post-auth hand-off: the auth gate in `_layout.tsx` detects the new session
 * and routes the user to onboarding (if the profile/goal is not yet set) or
 * directly to Today (returning user with a complete profile). The `onAuthenticated`
 * callback is a no-op since navigation is entirely driven by the gate.
 */
import { SignInScreen } from "@/components/SignInScreen";

export default function SignInRoute() {
  return <SignInScreen onAuthenticated={() => {}} />;
}
