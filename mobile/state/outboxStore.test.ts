import type { OutboxEntry } from "./outbox";

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

beforeEach(() => mockFs.clear());

describe("fileOutboxStore", () => {
  it("persists and reloads a user's queue across a store reload", async () => {
    await fileOutboxStore.save(USER_A, [entry()]);

    // A fresh load (simulating an app restart) sees the durably-stored entry.
    const loaded = await fileOutboxStore.load(USER_A);
    expect(loaded).toHaveLength(1);
    expect(loaded[0]).toMatchObject({
      idempotencyKey: "key-1",
      syncState: "queued",
      rawText: "two eggs",
    });
  });

  it("returns an empty queue when nothing is stored", async () => {
    expect(await fileOutboxStore.load(USER_A)).toEqual([]);
  });

  it("scopes storage per user — one user's queue never leaks to another", async () => {
    await fileOutboxStore.save(USER_A, [entry({ userId: USER_A })]);

    expect(await fileOutboxStore.load(USER_B)).toEqual([]);
    expect(await fileOutboxStore.load(USER_A)).toHaveLength(1);
  });

  it("drops entries owned by a different user (defence in depth)", async () => {
    // Hand-write a file containing a foreign-owned entry under USER_A's name.
    await fileOutboxStore.save(USER_A, [
      entry({ userId: USER_A, idempotencyKey: "mine" }),
      entry({ userId: USER_B, idempotencyKey: "theirs" }),
    ]);

    const loaded = await fileOutboxStore.load(USER_A);
    expect(loaded.map((e) => e.idempotencyKey)).toEqual(["mine"]);
  });

  it("clears a user's queue on sign-out, leaving no residue", async () => {
    await fileOutboxStore.save(USER_A, [entry()]);
    await fileOutboxStore.clear(USER_A);

    expect(await fileOutboxStore.load(USER_A)).toEqual([]);
  });

  it("saving an empty queue removes the file rather than leaving residue", async () => {
    await fileOutboxStore.save(USER_A, [entry()]);
    await fileOutboxStore.save(USER_A, []);

    expect(mockFs.size).toBe(0);
    expect(await fileOutboxStore.load(USER_A)).toEqual([]);
  });

  it("fails closed to an empty queue on corrupt JSON", async () => {
    mockFs.set(`fatty-outbox-${USER_A}.json`, "{ not json ]");
    expect(await fileOutboxStore.load(USER_A)).toEqual([]);
  });
});
