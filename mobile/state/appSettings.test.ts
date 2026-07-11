/**
 * Tests for the on-device appearance settings store.
 *
 * Appearance is a non-sensitive display preference persisted to a normal JSON
 * file via expo-file-system. These tests pin the on-device file name (the
 * Slacks-branded identifier) and the round-trip behaviour.
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
import { fileAppSettingsStore } from "./appSettings";

afterEach(() => {
  for (const key of Object.keys(mockFiles)) delete mockFiles[key];
});

describe("fileAppSettingsStore", () => {
  it("writes the on-device settings to slacks-app-settings.json", async () => {
    await fileAppSettingsStore.setAppearance("dark");
    expect(Object.keys(mockFiles)).toEqual(["slacks-app-settings.json"]);
  });

  it("defaults to system when nothing is stored", async () => {
    await expect(fileAppSettingsStore.getAppearance()).resolves.toBe("system");
  });

  it("round-trips a saved appearance override", async () => {
    await fileAppSettingsStore.setAppearance("light");
    await expect(fileAppSettingsStore.getAppearance()).resolves.toBe("light");
  });
});
