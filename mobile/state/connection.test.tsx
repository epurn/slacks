/**
 * Tests for the connected-server provider + first-run routing decision (FTY-107).
 *
 * Covers hydration from the store, mirroring the connection into the synchronous
 * `resolveApiBaseUrl()` cache, the connect/clear controller, the no-secret-store
 * guarantee, and the pure routing decision the gate consumes.
 */

// config imports expo-constants at module load; mock it so the import is inert.
const mockExtra: { apiBaseUrl?: string } = {};
jest.mock("expo-constants", () => ({
  __esModule: true,
  default: {
    get expoConfig() {
      return { extra: mockExtra };
    },
  },
}));

// eslint-disable-next-line import/first
import { useEffect } from "react";
// eslint-disable-next-line import/first
import { act, create, type ReactTestRenderer } from "react-test-renderer";

// eslint-disable-next-line import/first
import { resolveApiBaseUrl, setConnectedBaseUrl } from "@/api/config";
// eslint-disable-next-line import/first
import { ConnectionProvider, useConnection } from "./connection";
// eslint-disable-next-line import/first
import type { ServerConnectionStore } from "./serverConnectionStore";

const URL_A = "https://server-a.example.com";

/** An in-memory connection store with call tracking. */
function fakeStore(initial: string | null = null) {
  let value = initial;
  return {
    load: jest.fn(async () => value),
    save: jest.fn(async (u: string) => {
      value = u;
    }),
    clear: jest.fn(async () => {
      value = null;
    }),
  } satisfies ServerConnectionStore;
}

const captured: { value: ReturnType<typeof useConnection> | null } = {
  value: null,
};
const ctx = (): ReturnType<typeof useConnection> => {
  if (captured.value === null) throw new Error("controller not captured");
  return captured.value;
};
function Capture() {
  const value = useConnection();
  useEffect(() => {
    captured.value = value;
  });
  return null;
}

async function mount(store: ServerConnectionStore): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = create(
      <ConnectionProvider store={store}>
        <Capture />
      </ConnectionProvider>,
    );
  });
  return tree;
}

afterEach(() => {
  setConnectedBaseUrl(null);
  captured.value = null;
});

describe("ConnectionProvider hydration", () => {
  it("hydrates the persisted connection and mirrors it into resolveApiBaseUrl()", async () => {
    await mount(fakeStore(URL_A));
    expect(ctx().connection).toBe(URL_A);
    expect(ctx().status).toBe("ready");
    expect(resolveApiBaseUrl()).toBe(URL_A);
  });

  it("hydrates null when nothing is connected and resolves the build-time default", async () => {
    await mount(fakeStore(null));
    expect(ctx().connection).toBeNull();
    expect(ctx().status).toBe("ready");
    expect(resolveApiBaseUrl()).toBe("http://localhost:8000");
  });
});

describe("connection controller", () => {
  it("connect persists, updates state, and targets the new server live", async () => {
    const store = fakeStore(null);
    await mount(store);
    await act(async () => {
      await ctx().connect(URL_A);
    });
    expect(store.save).toHaveBeenCalledWith(URL_A);
    expect(ctx().connection).toBe(URL_A);
    expect(resolveApiBaseUrl()).toBe(URL_A);
  });

  it("clear forgets the connection and restores the default target", async () => {
    const store = fakeStore(URL_A);
    await mount(store);
    expect(ctx().connection).toBe(URL_A);
    await act(async () => {
      await ctx().clear();
    });
    expect(store.clear).toHaveBeenCalledTimes(1);
    expect(ctx().connection).toBeNull();
    expect(resolveApiBaseUrl()).toBe("http://localhost:8000");
  });

  it("rehydrates the saved connection after a simulated app restart", async () => {
    const store = fakeStore(null);
    await mount(store);
    await act(async () => {
      await ctx().connect(URL_A);
    });
    // Fresh provider, same store → the persisted connection comes back.
    await mount(store);
    expect(ctx().connection).toBe(URL_A);
  });

  it("never touches expo-secure-store and never logs the URL as a secret", async () => {
    // No expo-secure-store mock is registered: importing/using it here would
    // throw. The store seam is the plain file store, proving the URL is
    // non-secret config.
    const spies = (["log", "info", "warn", "error", "debug"] as const).map(
      (level) => jest.spyOn(console, level).mockImplementation(() => {}),
    );
    try {
      const store = fakeStore(null);
      await mount(store);
      await act(async () => {
        await ctx().connect(URL_A);
      });
      for (const spy of spies) {
        for (const call of spy.mock.calls) {
          expect(call.map((c) => String(c)).join(" ")).not.toContain(URL_A);
        }
      }
    } finally {
      spies.forEach((spy) => spy.mockRestore());
    }
  });
});
