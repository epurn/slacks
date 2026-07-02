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
import { secureGoalDirectionStore } from "./goalDirectionStore";

const setItemAsync = SecureStore.setItemAsync as jest.Mock;
const getItemAsync = SecureStore.getItemAsync as jest.Mock;
const deleteItemAsync = SecureStore.deleteItemAsync as jest.Mock;

const USER = "11111111-1111-1111-1111-111111111111";

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

describe("secureGoalDirectionStore", () => {
  it("round-trips the direction and userId across a store reload", async () => {
    await secureGoalDirectionStore.save(USER, "gain");
    expect(await secureGoalDirectionStore.load()).toEqual({
      userId: USER,
      direction: "gain",
    });
  });

  it("persists the record only through expo-secure-store, as one JSON value", async () => {
    await secureGoalDirectionStore.save(USER, "maintain");
    expect(setItemAsync).toHaveBeenCalledTimes(1);
    const [key, value] = setItemAsync.mock.calls[0] as [string, string];
    expect(typeof key).toBe("string");
    expect(JSON.parse(value)).toEqual({ userId: USER, direction: "maintain" });
  });

  it("overwrites the prior record on a new save (single key)", async () => {
    await secureGoalDirectionStore.save(USER, "loss");
    await secureGoalDirectionStore.save(USER, "gain");
    expect(await secureGoalDirectionStore.load()).toEqual({
      userId: USER,
      direction: "gain",
    });
  });

  it("clears the record so load returns null", async () => {
    await secureGoalDirectionStore.save(USER, "loss");
    await secureGoalDirectionStore.clear();
    expect(deleteItemAsync).toHaveBeenCalledWith(storedKey());
    expect(await secureGoalDirectionStore.load()).toBeNull();
  });

  it("returns null when there is no stored record", async () => {
    expect(await secureGoalDirectionStore.load()).toBeNull();
  });

  it("returns null for a corrupt (non-JSON) record", async () => {
    await secureGoalDirectionStore.save(USER, "loss");
    mockKeychain.set(storedKey(), "not-json{");
    expect(await secureGoalDirectionStore.load()).toBeNull();
  });

  it("returns null for a record with an unknown direction value", async () => {
    await secureGoalDirectionStore.save(USER, "loss");
    mockKeychain.set(
      storedKey(),
      JSON.stringify({ userId: USER, direction: "sideways" }),
    );
    expect(await secureGoalDirectionStore.load()).toBeNull();
  });

  it("returns null for a record missing the userId (no half record)", async () => {
    await secureGoalDirectionStore.save(USER, "loss");
    mockKeychain.set(storedKey(), JSON.stringify({ direction: "loss" }));
    expect(await secureGoalDirectionStore.load()).toBeNull();
  });

  it("returns null on a keychain read failure (fail closed)", async () => {
    getItemAsync.mockRejectedValueOnce(new Error("keychain unavailable"));
    expect(await secureGoalDirectionStore.load()).toBeNull();
  });
});
