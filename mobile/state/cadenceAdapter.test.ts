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
import { fileCadenceStore } from "./cadenceAdapter";

/** The single file name the store just wrote (tests inspect it opaquely). */
function onlyFileName(): string {
  const names = [...mockFs.keys()];
  expect(names).toHaveLength(1);
  return names[0];
}

beforeEach(() => mockFs.clear());

describe("fileCadenceStore", () => {
  it("names the on-device cadence file slacks-cadence.json", async () => {
    await fileCadenceStore.setCadence("weekly");
    expect(onlyFileName()).toBe("slacks-cadence.json");
  });

  it("persists and reloads the cadence preference across a store reload", async () => {
    await fileCadenceStore.setCadence("biweekly");
    expect(await fileCadenceStore.getCadence()).toBe("biweekly");
  });

  it("persists and reloads the last weigh-in date across a store reload", async () => {
    await fileCadenceStore.setLastWeighInDate("2026-07-11");
    expect(await fileCadenceStore.getLastWeighInDate()).toBe("2026-07-11");
  });

  it("returns null defaults when nothing is stored", async () => {
    expect(await fileCadenceStore.getCadence()).toBeNull();
    expect(await fileCadenceStore.getLastWeighInDate()).toBeNull();
  });
});
