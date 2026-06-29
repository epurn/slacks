import { useRouter } from "expo-router";

import { SignInScreen } from "@/components/SignInScreen";

/**
 * Sign-in / create-account route (`/signin`) — the auth step of the
 * self-host-first first run (FTY-091). Thin wrapper: the testable screen lives
 * in `SignInScreen`. The root layout's auth gate (`state/authRouting`) routes a
 * connected-but-signed-out launch here.
 *
 * Post-auth hand-off: the design routes a first run to onboarding (goal/profile
 * unset) before Today (FTY-103). Onboarding does not exist yet, so for now a
 * successful auth lands on Today; when FTY-103 ships, this callback chooses
 * onboarding-vs-Today.
 */
export default function SignInRoute() {
  const router = useRouter();
  return <SignInScreen onAuthenticated={() => router.replace("/")} />;
}
