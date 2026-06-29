/**
 * The connected-server seam (FTY-107).
 *
 * Fatty is self-host-first (UX design §4d): before anyone can sign in, the app
 * must be pointed at the user's own Fatty server. That connection — a single
 * non-secret base URL — is what this provider owns. It is the network target
 * every later request (including the FTY-091 credentials) is sent to, so it is
 * established deliberately on the connect screen after validation + a
 * reachability probe, then persisted.
 *
 * `ConnectionProvider` hydrates the persisted connection from the on-device
 * store on launch and mirrors it into the synchronous `resolveApiBaseUrl()`
 * cache (`api/config.ts`), so every existing API client targets the connected
 * server with no rewiring. It exposes a controller (`connect` / `clear`) the
 * connect screen drives, and a `status` + `connection` the first-run routing and
 * the FTY-091 sign-in gate consume. `useConnection()` returns the current base
 * URL (or `null`) and the hydration status.
 *
 * The server URL is **non-secret configuration**: it lives in normal on-device
 * storage, never the secure token store, and is never logged as a secret. No
 * credential is handled here.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { setConnectedBaseUrl } from "@/api/config";
import {
  fileServerConnectionStore,
  type ServerConnectionStore,
} from "@/state/serverConnectionStore";

/** Whether the provider has finished its launch-time hydration from storage. */
export type ConnectionStatus = "hydrating" | "ready";

interface ConnectionContextValue {
  /** The connected server base URL, or `null` when no server is connected. */
  readonly connection: string | null;
  /** Whether the persisted connection has been hydrated from storage yet. */
  readonly status: ConnectionStatus;
  /** Persist a validated base URL as the connected server and target it live. */
  connect(baseUrl: string): Promise<void>;
  /** Forget the connected server (the "change / clear server" affordance). */
  clear(): Promise<void>;
}

function notInProvider(): never {
  throw new Error("useConnection must be used within a ConnectionProvider");
}

const ConnectionContext = createContext<ConnectionContextValue>({
  connection: null,
  status: "ready",
  connect: notInProvider,
  clear: notInProvider,
});

/**
 * Provide the connected-server state to the tree. On mount it hydrates from the
 * connection store and mirrors the value into the `resolveApiBaseUrl()` cache;
 * the controller methods persist/clear the connection and keep both the cache
 * and the in-memory state in sync.
 *
 * `store` is injectable so tests can drive the controller against an in-memory
 * store without the platform filesystem.
 */
export function ConnectionProvider({
  children,
  store = fileServerConnectionStore,
}: {
  children: ReactNode;
  store?: ServerConnectionStore;
}) {
  const [connection, setConnection] = useState<string | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("hydrating");

  useEffect(() => {
    let active = true;
    void store.load().then((loaded) => {
      if (!active) return;
      setConnectedBaseUrl(loaded);
      setConnection(loaded);
      setStatus("ready");
    });
    return () => {
      active = false;
    };
  }, [store]);

  const connect = useCallback(
    async (baseUrl: string) => {
      await store.save(baseUrl);
      setConnectedBaseUrl(baseUrl);
      setConnection(baseUrl);
    },
    [store],
  );

  const clear = useCallback(async () => {
    await store.clear();
    setConnectedBaseUrl(null);
    setConnection(null);
  }, [store]);

  const value = useMemo<ConnectionContextValue>(
    () => ({ connection, status, connect, clear }),
    [connection, status, connect, clear],
  );

  return (
    <ConnectionContext.Provider value={value}>
      {children}
    </ConnectionContext.Provider>
  );
}

/**
 * The connected-server state + controller: the current `connection` base URL (or
 * `null`), the hydration `status`, and `connect` / `clear`. The connect screen
 * and the first-run routing consume this.
 *
 * The signed-out routing decision (connect → sign-in → app) lives in the unified
 * `resolveAuthRedirect` (`state/authRouting`), which composes this connection
 * status with the session status so all three states route from one place.
 */
export function useConnection(): ConnectionContextValue {
  return useContext(ConnectionContext);
}
