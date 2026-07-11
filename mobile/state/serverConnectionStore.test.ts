/**
 * Tests for the on-device connected-server store (FTY-107).
 *
 * The server URL is non-secret config: it persists to a normal JSON file via
 * expo-file-system, never the secure token store. A missing or corrupt file is
 * treated as no connection (`null`) so a first launch routes to the connect
 * screen rather than failing.
 */

// In-memory filesystem keyed by file name; prefixed "mock" for the jest factory.
const mockFiles: Record<string, string> = {};

jest.mock("expo-file-system", () => {
  class File {
    private readonly key: string;
    constructor(_dir: unknown, name: string) {
      this.key = name;
    }
    get exists(): boolean {
      return Object.prototype.hasOwnProperty.call(mockFiles, this.key);
    }
    async text(): Promise<string> {
      return mockFiles[this.key];
    }
    write(content: string): void {
      mockFiles[this.key] = content;
    }
    delete(): void {
      delete mockFiles[this.key];
    }
  }
  return { File, Paths: { document: "/doc" } };
});

// eslint-disable-next-line import/first
import { fileServerConnectionStore } from "./serverConnectionStore";

afterEach(() => {
  for (const key of Object.keys(mockFiles)) delete mockFiles[key];
});

describe("fileServerConnectionStore", () => {
  it("returns null when nothing is stored", async () => {
    await expect(fileServerConnectionStore.load()).resolves.toBeNull();
  });

  it("round-trips a saved base URL", async () => {
    await fileServerConnectionStore.save("https://my-server.example.com");
    await expect(fileServerConnectionStore.load()).resolves.toBe(
      "https://my-server.example.com",
    );
  });

  it("clears a stored connection", async () => {
    await fileServerConnectionStore.save("https://my-server.example.com");
    await fileServerConnectionStore.clear();
    await expect(fileServerConnectionStore.load()).resolves.toBeNull();
  });

  it("does not persist the URL to the secure token store key shape", async () => {
    await fileServerConnectionStore.save("https://my-server.example.com");
    // The non-secret connection lives in a plain document file, not under any
    // keychain/secure-store key.
    expect(Object.keys(mockFiles)).toEqual(["slacks-server-connection.json"]);
  });

  it("treats a corrupt file as no connection", async () => {
    mockFiles["slacks-server-connection.json"] = "{ not json";
    await expect(fileServerConnectionStore.load()).resolves.toBeNull();
  });

  it("treats a stored empty string as no connection", async () => {
    mockFiles["slacks-server-connection.json"] = JSON.stringify({ baseUrl: "" });
    await expect(fileServerConnectionStore.load()).resolves.toBeNull();
  });
});
