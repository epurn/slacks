import type { OutboxEntry, OutboxOwner } from "./outbox";

// In-memory fake of the expo-file-system File/Paths API, keyed by file name.
const mockFs = new Map<string, string>();

jest.mock("expo-file-system", () => {
  class File {
    name: string;
    constructor(_dir: unknown, name: string) {
      this.name = name;
    }
    get exists(): boolean {
      return mockFs.has(this.name);
    }
    async text(): Promise<string> {
      return mockFs.get(this.name) ?? "";
    }
    write(content: string): void {
      mockFs.set(this.name, content);
    }
    delete(): void {
      mockFs.delete(this.name);
    }
  }
  return { File, Paths: { document: { uri: "file:///docs/" } } };
});

// Import after the mock is registered (jest.mock is hoisted, but the import of
// the module under test must observe the mocked native module).
// eslint-disable-next-line import/first
import { fileOutboxStore } from "./outboxStore";

const USER_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa";
const USER_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb";
const SERVER_1 = "https://one.example.test";
const SERVER_2 = "https://two.example.test";

const OWNER_A: OutboxOwner = { serverUrl: SERVER_1, userId: USER_A };
const OWNER_B: OutboxOwner = { serverUrl: SERVER_1, userId: USER_B };
// Same user id as OWNER_A but on a *different* self-hosted server.
const OWNER_A_OTHER_SERVER: OutboxOwner = { serverUrl: SERVER_2, userId: USER_A };

function entry(overrides: Partial<OutboxEntry> = {}): OutboxEntry {
  return {
    idempotencyKey: "key-1",
    userId: USER_A,
    rawText: "two eggs",
    capturedAt: "2026-06-28T08:00:00Z",
    syncState: "queued",
    ...overrides,
  };
}

/** The single file name the store just wrote (tests inspect it opaquely). */
function onlyFileName(): string {
  const names = [...mockFs.keys()];
  expect(names).toHaveLength(1);
  return names[0];
}

beforeEach(() => mockFs.clear());

describe("fileOutboxStore", () => {
  it("persists and reloads an owner's queue across a store reload", async () => {
    await fileOutboxStore.save(OWNER_A, [entry()]);

    // A fresh load (simulating an app restart) sees the durably-stored entry.
    const loaded = await fileOutboxStore.load(OWNER_A);
    expect(loaded).toHaveLength(1);
    expect(loaded[0]).toMatchObject({
      idempotencyKey: "key-1",
      syncState: "queued",
      rawText: "two eggs",
    });
  });

  it("names the on-device queue file with the slacks-outbox- prefix", async () => {
    await fileOutboxStore.save(OWNER_A, [entry()]);
    expect(onlyFileName()).toMatch(/^slacks-outbox-.+\.json$/);
  });

  it("returns an empty queue when nothing is stored", async () => {
    expect(await fileOutboxStore.load(OWNER_A)).toEqual([]);
  });

  it("scopes storage per user — one user's queue never leaks to another", async () => {
    await fileOutboxStore.save(OWNER_A, [entry({ userId: USER_A })]);

    expect(await fileOutboxStore.load(OWNER_B)).toEqual([]);
    expect(await fileOutboxStore.load(OWNER_A)).toHaveLength(1);
  });

  it("scopes storage per server — the same user id on two servers has separate queues (FTY-277)", async () => {
    await fileOutboxStore.save(OWNER_A, [entry({ idempotencyKey: "on-server-1" })]);

    // Same user id, different self-hosted server: must not see server 1's queue.
    expect(await fileOutboxStore.load(OWNER_A_OTHER_SERVER)).toEqual([]);

    // And writing under the second server must not clobber the first server's file.
    await fileOutboxStore.save(OWNER_A_OTHER_SERVER, [
      entry({ idempotencyKey: "on-server-2" }),
    ]);
    expect((await fileOutboxStore.load(OWNER_A)).map((e) => e.idempotencyKey)).toEqual(
      ["on-server-1"],
    );
    expect(
      (await fileOutboxStore.load(OWNER_A_OTHER_SERVER)).map((e) => e.idempotencyKey),
    ).toEqual(["on-server-2"]);
    // Two distinct owners ⇒ two distinct files.
    expect(mockFs.size).toBe(2);
  });

  it("treats cosmetically-different spellings of the same server as one owner", async () => {
    await fileOutboxStore.save(OWNER_A, [entry({ idempotencyKey: "canonical" })]);

    // Trailing slash + upper-case host spell the same server: load finds the file.
    const loaded = await fileOutboxStore.load({
      serverUrl: "HTTPS://One.Example.Test/",
      userId: USER_A,
    });
    expect(loaded.map((e) => e.idempotencyKey)).toEqual(["canonical"]);
    expect(mockFs.size).toBe(1);
  });

  it("keeps path-case-distinct servers on separate queues for the same user id (FTY-277)", async () => {
    // A self-hosted Slacks can live under a base path, and paths are
    // case-sensitive: https://host/Slacks and https://host/slacks are two distinct
    // servers. The owner key lowercases only scheme + host, so these must not
    // collapse onto one file even though the user id is identical.
    const upper: OutboxOwner = {
      serverUrl: "https://self.example.test/Slacks",
      userId: USER_A,
    };
    const lower: OutboxOwner = {
      serverUrl: "https://self.example.test/slacks",
      userId: USER_A,
    };
    await fileOutboxStore.save(upper, [entry({ idempotencyKey: "upper-path" })]);
    await fileOutboxStore.save(lower, [entry({ idempotencyKey: "lower-path" })]);

    expect((await fileOutboxStore.load(upper)).map((e) => e.idempotencyKey)).toEqual([
      "upper-path",
    ]);
    expect((await fileOutboxStore.load(lower)).map((e) => e.idempotencyKey)).toEqual([
      "lower-path",
    ]);
    expect(mockFs.size).toBe(2);
  });

  it("drops entries owned by a different user (defence in depth)", async () => {
    // Hand-write a file containing a foreign-owned entry under OWNER_A's file.
    await fileOutboxStore.save(OWNER_A, [
      entry({ userId: USER_A, idempotencyKey: "mine" }),
      entry({ userId: USER_B, idempotencyKey: "theirs" }),
    ]);

    const loaded = await fileOutboxStore.load(OWNER_A);
    expect(loaded.map((e) => e.idempotencyKey)).toEqual(["mine"]);
  });

  it("clears an owner's queue on explicit purge, leaving no residue", async () => {
    await fileOutboxStore.save(OWNER_A, [entry()]);
    await fileOutboxStore.clear(OWNER_A);

    expect(await fileOutboxStore.load(OWNER_A)).toEqual([]);
    expect(mockFs.size).toBe(0);
  });

  it("saving an empty queue removes the file rather than leaving residue", async () => {
    await fileOutboxStore.save(OWNER_A, [entry()]);
    await fileOutboxStore.save(OWNER_A, []);

    expect(mockFs.size).toBe(0);
    expect(await fileOutboxStore.load(OWNER_A)).toEqual([]);
  });

  it("stores no bearer token or credential in the file name or contents", async () => {
    await fileOutboxStore.save(OWNER_A, [entry()]);
    const name = onlyFileName();
    const contents = mockFs.get(name) ?? "";
    // The owner's server URL and user id are enough to scope the file; nothing
    // token-shaped is encoded into the name or written into the payload.
    expect(name).not.toContain(SERVER_1);
    expect(`${name} ${contents}`).not.toMatch(/token|bearer|password|secret/i);
  });

  it("fails closed to an empty queue on corrupt JSON", async () => {
    // Learn the real file name by writing a valid queue first, then corrupt it.
    await fileOutboxStore.save(OWNER_A, [entry()]);
    mockFs.set(onlyFileName(), "{ not json ]");

    expect(await fileOutboxStore.load(OWNER_A)).toEqual([]);
  });
});
