import { useRouter } from "expo-router";

import { ConnectScreen } from "@/components/ConnectScreen";

/**
 * Connect-to-your-server route (`/connect`) — the self-host-first first step
 * (FTY-107). Thin wrapper: the testable screen lives in `ConnectScreen`.
 *
 * After a successful connect the flow hands off to sign-in (FTY-091). That route
 * does not exist yet, so for now we return to the app root; FTY-091 retargets
 * `onConnected` to the sign-in screen and inserts the auth gate in front of it.
 */
export default function ConnectRoute() {
  const router = useRouter();
  return <ConnectScreen onConnected={() => router.replace("/")} />;
}
