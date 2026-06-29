// In-memory fake of the expo-secure-store keychain API, keyed by store key.
// `mockKeychain` is mock-prefixed so the jest.mock factory may reference it.
const mockKeychain = new Map<string, string>();

jest.mock("expo-secure-store", () => ({
  setItemAsync: jest.fn(async (key: string, value: string) => {
    mockKeychain.set(key, value);
  }),
  getItemAsync: jest.fn(async (key: string) => mockKeychain.get(key) ?? null),
  deleteItemAsync: jest.fn(async (key: string) => {
    mockKeychain.delete(key);
  }),
}));

// Import after the mock is registered (the module under test must observe it).
// eslint-disable-next-line import/first
import * as SecureStore from "expo-secure-store";
// eslint-disable-next-line import/first
import { secureSessionStore } from "./sessionStore";
// eslint-disable-next-line import/first
import type { SessionRecord } from "./session";

const setItemAsync = SecureStore.setItemAsync as jest.Mock;
const getItemAsync = SecureStore.getItemAsync as jest.Mock;
const deleteItemAsync = SecureStore.deleteItemAsync as jest.Mock;

const SESSION: SessionRecord = {
  serverUrl: "https://fatty.example.test",
  token: "header.signature",
  userId: "11111111-1111-1111-1111-111111111111",
};

/** The single key the store persists under. */
function storedKey(): string {
  return setItemAsync.mock.calls[0]?.[0] as string;
}

beforeEach(() => {
  mockKeychain.clear();
  setItemAsync.mockClear();
  getItemAsync.mockClear();
  deleteItemAsync.mockClear();
});

describe("secureSessionStore", () => {
  it("round-trips the full session record across a store reload", async () => {
    await secureSessionStore.save(SESSION);
    expect(await secureSessionStore.load()).toEqual(SESSION);
  });

  it("persists the record only through expo-secure-store, as one JSON value", async () => {
    await secureSessionStore.save(SESSION);
    expect(setItemAsync).toHaveBeenCalledTimes(1);
    const [key, value] = setItemAsync.mock.calls[0] as [string, string];
    expect(typeof key).toBe("string");
    expect(JSON.parse(value)).toEqual(SESSION);
  });

  it("clears the record so load returns null", async () => {
    await secureSessionStore.save(SESSION);
    await secureSessionStore.clear();
    expect(deleteItemAsync).toHaveBeenCalledWith(storedKey());
    expect(await secureSessionStore.load()).toBeNull();
  });

  it("returns null when there is no stored record", async () => {
    expect(await secureSessionStore.load()).toBeNull();
  });

  it("returns null for a corrupt (non-JSON) record", async () => {
    await secureSessionStore.save(SESSION);
    mockKeychain.set(storedKey(), "not-json{");
    expect(await secureSessionStore.load()).toBeNull();
  });

  it("returns null for a partial record missing a field (no half session)", async () => {
    await secureSessionStore.save(SESSION);
    mockKeychain.set(
      storedKey(),
      JSON.stringify({ token: SESSION.token, userId: SESSION.userId }),
    );
    expect(await secureSessionStore.load()).toBeNull();
  });

  it("returns null when a field is present but empty", async () => {
    await secureSessionStore.save(SESSION);
    mockKeychain.set(storedKey(), JSON.stringify({ ...SESSION, serverUrl: "" }));
    expect(await secureSessionStore.load()).toBeNull();
  });

  it("drops unknown extra keys on load", async () => {
    await secureSessionStore.save(SESSION);
    mockKeychain.set(
      storedKey(),
      JSON.stringify({ ...SESSION, rogue: "extra" }),
    );
    expect(await secureSessionStore.load()).toEqual(SESSION);
  });

  it("fails closed to null when the keychain read throws", async () => {
    getItemAsync.mockRejectedValueOnce(new Error("keychain unavailable"));
    expect(await secureSessionStore.load()).toBeNull();
  });

  it("never logs the token", async () => {
    const spies = (["log", "info", "warn", "error", "debug"] as const).map(
      (level) => jest.spyOn(console, level).mockImplementation(() => {}),
    );
    try {
      await secureSessionStore.save(SESSION);
      await secureSessionStore.load();
      await secureSessionStore.clear();
      for (const spy of spies) {
        for (const call of spy.mock.calls) {
          expect(call.map((c) => String(c)).join(" ")).not.toContain(
            SESSION.token,
          );
        }
      }
    } finally {
      spies.forEach((spy) => spy.mockRestore());
    }
  });
});
