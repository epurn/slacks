import { useEffect } from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

// The provider uses an injected store/authClient in these tests, so the real
// keychain is never touched; mock it as a no-op to keep the import inert.
jest.mock("expo-secure-store", () => ({
  setItemAsync: async () => {},
  getItemAsync: async () => null,
  deleteItemAsync: async () => {},
}));

// eslint-disable-next-line import/first
import {
  SessionProvider,
  toApiSession,
  toProfileSession,
  useSessionController,
  type AuthClient,
  type SessionRecord,
} from "./session";
// eslint-disable-next-line import/first
import type { SessionStore } from "./sessionStore";
// eslint-disable-next-line import/first
import { notifyUnauthorized, setUnauthorizedHandler } from "@/api/client";
// eslint-disable-next-line import/first
import { resolveAuthRedirect } from "./authRouting";

// The unauthorized handler is a module-level singleton in api/client; restore
// the safe no-op after each test so a torn-down provider can't leak a handler.
afterEach(() => {
  setUnauthorizedHandler(null);
});

const RECORD: SessionRecord = {
  serverUrl: "https://fatty.example.test",
  token: "header.signature",
  userId: "11111111-1111-1111-1111-111111111111",
};

/** A controllable in-memory session store with call tracking. */
function fakeStore(initial: SessionRecord | null = null) {
  let value = initial;
  return {
    save: jest.fn(async (s: SessionRecord) => {
      value = s;
    }),
    load: jest.fn(async () => value),
    clear: jest.fn(async () => {
      value = null;
    }),
  } satisfies SessionStore;
}

/** An auth client that returns a server-bound record without any network. */
function fakeAuth(record: SessionRecord = RECORD) {
  return {
    createAccount: jest.fn(async (serverUrl: string) => ({
      ...record,
      serverUrl,
    })),
    signIn: jest.fn(async (serverUrl: string) => ({ ...record, serverUrl })),
  } satisfies AuthClient;
}

// Captured controller value from the most recent render. Held on a const object
// (not a reassigned free variable) so the render stays lint-clean.
const captured: { value: ReturnType<typeof useSessionController> | null } = {
  value: null,
};
const ctx = (): ReturnType<typeof useSessionController> => {
  if (captured.value === null) {
    throw new Error("controller not captured");
  }
  return captured.value;
};
function Capture() {
  const value = useSessionController();
  // Record outside render (effects run after commit), so the capture is not a
  // render-time side effect.
  useEffect(() => {
    captured.value = value;
  });
  return null;
}

async function mount(props: {
  store?: SessionStore;
  authClient?: AuthClient;
}): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(
      <SessionProvider {...props}>
        <Capture />
      </SessionProvider>,
    );
  });
  return tree;
}

describe("SessionProvider hydration", () => {
  it("hydrates the persisted session from the store on launch", async () => {
    await mount({ store: fakeStore(RECORD), authClient: fakeAuth() });
    expect(ctx().session).toEqual(RECORD);
    expect(ctx().status).toBe("ready");
  });

  it("hydrates null when there is no stored session", async () => {
    await mount({ store: fakeStore(null), authClient: fakeAuth() });
    expect(ctx().session).toBeNull();
    expect(ctx().status).toBe("ready");
  });
});

describe("session controller", () => {
  it("signIn authenticates the bound server, persists, and updates the session", async () => {
    const store = fakeStore(null);
    const auth = fakeAuth();
    await mount({ store, authClient: auth });

    await act(async () => {
      await ctx().signIn(RECORD.serverUrl, "alice@example.com", "a-good-password");
    });

    expect(auth.signIn).toHaveBeenCalledWith(
      RECORD.serverUrl,
      "alice@example.com",
      "a-good-password",
    );
    expect(store.save).toHaveBeenCalledWith(RECORD);
    expect(ctx().session).toEqual(RECORD);
  });

  it("createAccount persists and updates the session", async () => {
    const store = fakeStore(null);
    const auth = fakeAuth();
    await mount({ store, authClient: auth });

    await act(async () => {
      await ctx().createAccount(RECORD.serverUrl, "alice@example.com", "pw-pw-pw1");
    });

    expect(auth.createAccount).toHaveBeenCalledTimes(1);
    expect(store.save).toHaveBeenCalledWith(RECORD);
    expect(ctx().session).toEqual(RECORD);
  });

  it("signOut clears the store and drops the session to null", async () => {
    const store = fakeStore(RECORD);
    await mount({ store, authClient: fakeAuth() });
    expect(ctx().session).toEqual(RECORD);

    await act(async () => {
      await ctx().signOut();
    });

    expect(store.clear).toHaveBeenCalledTimes(1);
    expect(ctx().session).toBeNull();
  });

  it("rehydrates the saved session after a simulated app restart", async () => {
    // One store shared across two provider lifetimes: sign in, then remount.
    const store = fakeStore(null);
    await mount({ store, authClient: fakeAuth() });
    await act(async () => {
      await ctx().signIn(RECORD.serverUrl, "alice@example.com", "a-good-password");
    });

    // Fresh provider, same store → the persisted session comes back.
    await mount({ store, authClient: fakeAuth() });
    expect(ctx().session).toEqual(RECORD);
  });

  it("does not log the token when signing in", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map(
      (level) => jest.spyOn(console, level).mockImplementation(() => {}),
    );
    try {
      await mount({ store: fakeStore(null), authClient: fakeAuth() });
      await act(async () => {
        await ctx().signIn(RECORD.serverUrl, "alice@example.com", "secret-pw1");
      });
      for (const spy of spies) {
        for (const call of spy.mock.calls) {
          const text = call.map((c) => String(c)).join(" ");
          expect(text).not.toContain(RECORD.token);
          expect(text).not.toContain("secret-pw1");
        }
      }
    } finally {
      spies.forEach((spy) => spy.mockRestore());
    }
  });
});

describe("unauthorized-handler registration (FTY-274)", () => {
  it("registers signOut so an authenticated 401 clears the session", async () => {
    const store = fakeStore(RECORD);
    await mount({ store, authClient: fakeAuth() });
    expect(ctx().session).toEqual(RECORD);

    // Simulate the api client seeing a 401 on an authenticated request.
    await act(async () => {
      notifyUnauthorized();
    });

    expect(store.clear).toHaveBeenCalledTimes(1);
    expect(ctx().session).toBeNull();
  });

  it("drives the auth-redirect to the sign-in route once the 401 clears the session", async () => {
    const store = fakeStore(RECORD);
    await mount({ store, authClient: fakeAuth() });

    await act(async () => {
      notifyUnauthorized();
    });

    // With the session now null (and a server still connected), the existing
    // pure routing decision sends the user to sign-in — no _layout.tsx change.
    const target = resolveAuthRedirect({
      connectionStatus: "ready",
      connection: RECORD.serverUrl,
      sessionStatus: "ready",
      session: ctx().session,
      onboardingStatus: "checking",
      atConnect: false,
      atSignin: false,
      atOnboarding: false,
    });
    expect(ctx().session).toBeNull();
    expect(target).toBe("/signin");
  });

  it("is safe to invoke repeatedly — concurrent 401s do not throw or re-clear a cleared session", async () => {
    const store = fakeStore(RECORD);
    await mount({ store, authClient: fakeAuth() });

    await act(async () => {
      notifyUnauthorized();
      notifyUnauthorized();
      notifyUnauthorized();
    });

    // Every call runs signOut (idempotent); the session ends null and nothing throws.
    expect(store.clear).toHaveBeenCalledTimes(3);
    expect(ctx().session).toBeNull();
  });

  it("unregisters the handler on unmount so a 401 no longer clears a session it no longer owns", async () => {
    const store = fakeStore(RECORD);
    const tree = await mount({ store, authClient: fakeAuth() });

    await act(async () => {
      tree.unmount();
    });

    // After unmount the handler is the safe no-op again: notifying does nothing.
    await act(async () => {
      notifyUnauthorized();
    });
    expect(store.clear).not.toHaveBeenCalled();
  });
});

describe("base-URL binding", () => {
  it("toApiSession sources baseUrl from the session's bound server, not the default", () => {
    const api = toApiSession(RECORD);
    expect(api.baseUrl).toBe(RECORD.serverUrl);
    expect(api.baseUrl).not.toBe("http://localhost:8000");
    expect(api).toEqual({
      baseUrl: RECORD.serverUrl,
      token: RECORD.token,
      userId: RECORD.userId,
    });
  });

  it("toProfileSession binds the profile call to the session's server", () => {
    const profile = toProfileSession(RECORD);
    expect(profile.baseUrl).toBe(RECORD.serverUrl);
  });
});
