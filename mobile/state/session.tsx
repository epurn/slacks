/**
 * The authenticated-session seam (FTY-090).
 *
 * Fatty is self-host-first with no hosted instance (UX design §4d), so a
 * session is **bound to the user's own server**: the unit that persists is
 * `{ serverUrl, token, userId }`, not a token alone. A token issued by one
 * self-hosted server is meaningless against another, so the server URL the user
 * connected to is part of the session and is stored, hydrated, and cleared
 * atomically with the token.
 *
 * `SessionProvider` hydrates the session from the secure store on launch and
 * exposes a controller (`signIn` / `createAccount` / `signOut`) that the
 * connect / sign-in screens (FTY-091) drive. `useSession()` returns the current
 * `{ serverUrl, token, userId }` or `null`. The existing
 * `ProfileScreen`/`profile.ts` consumer keeps working unchanged: once a session
 * exists, profile persistence works with no edit to the form (the seam was
 * built for exactly this in FTY-021), now addressing the bound server instead
 * of static config.
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

import { createAccount, signIn } from "@/api/auth";
import type { ProfileSession } from "@/api/profile";
import { secureSessionStore, type SessionStore } from "@/state/sessionStore";

/**
 * The persisted session record: the bearer token plus the server it was minted
 * by and the resolved owner id. Stored as one atomic value (see `sessionStore`).
 */
export interface SessionRecord {
  readonly serverUrl: string;
  readonly token: string;
  readonly userId: string;
}

/** The signed-in session, or `null` when no one is signed in. */
export type Session = SessionRecord | null;

/** An authenticated session addressed at the session's bound server URL. */
export interface ApiSession {
  readonly baseUrl: string;
  readonly token: string;
  readonly userId: string;
}

/** The auth calls the controller drives; injectable for tests. */
export interface AuthClient {
  createAccount(
    serverUrl: string,
    email: string,
    password: string,
  ): Promise<SessionRecord>;
  signIn(
    serverUrl: string,
    email: string,
    password: string,
  ): Promise<SessionRecord>;
}

/** Whether the provider has finished its launch-time hydration from storage. */
export type SessionStatus = "hydrating" | "ready";

interface SessionContextValue {
  readonly session: Session;
  readonly status: SessionStatus;
  signIn(
    serverUrl: string,
    email: string,
    password: string,
  ): Promise<SessionRecord>;
  createAccount(
    serverUrl: string,
    email: string,
    password: string,
  ): Promise<SessionRecord>;
  signOut(): Promise<void>;
}

function notInProvider(): never {
  throw new Error("useSessionController must be used within a SessionProvider");
}

const SessionContext = createContext<SessionContextValue>({
  session: null,
  status: "ready",
  signIn: notInProvider,
  createAccount: notInProvider,
  signOut: notInProvider,
});

/** The real auth client backed by the FTY-020 endpoints. */
const defaultAuthClient: AuthClient = { createAccount, signIn };

/**
 * Provide the signed-in session to the tree. On mount it hydrates from the
 * secure store; the controller methods authenticate against the bound server,
 * persist the resulting record atomically, and update the in-memory session.
 *
 * `store` and `authClient` are injectable so tests can drive the controller
 * against a mocked `expo-secure-store` and a mocked `fetch`.
 */
export function SessionProvider({
  children,
  store = secureSessionStore,
  authClient = defaultAuthClient,
}: {
  children: ReactNode;
  store?: SessionStore;
  authClient?: AuthClient;
}) {
  const [session, setSession] = useState<Session>(null);
  const [status, setStatus] = useState<SessionStatus>("hydrating");

  useEffect(() => {
    let active = true;
    void store.load().then((loaded) => {
      if (!active) {
        return;
      }
      setSession(loaded);
      setStatus("ready");
    });
    return () => {
      active = false;
    };
  }, [store]);

  const handleSignIn = useCallback(
    async (serverUrl: string, email: string, password: string) => {
      const record = await authClient.signIn(serverUrl, email, password);
      await store.save(record);
      setSession(record);
      return record;
    },
    [authClient, store],
  );

  const handleCreateAccount = useCallback(
    async (serverUrl: string, email: string, password: string) => {
      const record = await authClient.createAccount(serverUrl, email, password);
      await store.save(record);
      setSession(record);
      return record;
    },
    [authClient, store],
  );

  const handleSignOut = useCallback(async () => {
    await store.clear();
    setSession(null);
  }, [store]);

  const value = useMemo<SessionContextValue>(
    () => ({
      session,
      status,
      signIn: handleSignIn,
      createAccount: handleCreateAccount,
      signOut: handleSignOut,
    }),
    [session, status, handleSignIn, handleCreateAccount, handleSignOut],
  );

  return (
    <SessionContext.Provider value={value}>{children}</SessionContext.Provider>
  );
}

/** The signed-in session, or `null`. Hydrated by `SessionProvider` on launch. */
export function useSession(): Session {
  return useContext(SessionContext).session;
}

/**
 * The session controller plus current state: `signIn` / `createAccount` /
 * `signOut`, the live `session`, and the hydration `status`. The connect /
 * sign-in screens (FTY-091) drive this.
 */
export function useSessionController(): SessionContextValue {
  return useContext(SessionContext);
}

/**
 * Combine a session with its bound server URL for an authenticated call. The
 * base URL is sourced from the session (the server the token was minted by),
 * not from static config, so a token is never replayed against a different
 * self-hosted server by a config swap. The returned shape is unchanged, so
 * `profile.ts` and `ProfileScreen` consume it without edit.
 */
export function toApiSession(session: SessionRecord): ApiSession {
  return {
    baseUrl: session.serverUrl,
    token: session.token,
    userId: session.userId,
  };
}

/** Combine a session with its bound server URL into a `ProfileSession`. */
export function toProfileSession(session: SessionRecord): ProfileSession {
  return toApiSession(session);
}
