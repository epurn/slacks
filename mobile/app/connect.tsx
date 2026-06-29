import { useRouter } from "expo-router";

import { ConnectScreen } from "@/components/ConnectScreen";

/**
 * Connect-to-your-server route (`/connect`) — the self-host-first first step
 * (FTY-107). Thin wrapper: the testable screen lives in `ConnectScreen`.
 *
 * After a successful connect the flow hands off to sign-in (FTY-091): the user
 * connects to their own server, then signs in or creates an account on it.
 */
export default function ConnectRoute() {
  const router = useRouter();
  return <ConnectScreen onConnected={() => router.replace("/signin")} />;
}
