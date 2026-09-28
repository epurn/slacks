/**
 * Tests for the sticky save-label-photos preference store (FTY-433).
 *
 * The preference decides the `?save=` retention flag on every label upload, so
 * these tests pin the security-relevant behaviour: the default is off, only a
 * literal stored `true` enables retention, a corrupt/unreadable file fails
 * closed, and the on-device file name is the Slacks-branded identifier (kept
 * separate from the appearance store so the two can't clobber each other).
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
  }
  return { File, Paths: { document: "/doc" } };
});

// eslint-disable-next-line import/first
import {
  DEFAULT_SAVE_LABEL_PHOTOS,
  fileLabelSavePreferenceStore,
} from "./labelSavePreference";

const FILE_NAME = "slacks-capture-preferences.json";

afterEach(() => {
  for (const key of Object.keys(mockFiles)) delete mockFiles[key];
});

describe("fileLabelSavePreferenceStore", () => {
  it("defaults to off (discard by default) when nothing is stored", async () => {
    expect(DEFAULT_SAVE_LABEL_PHOTOS).toBe(false);
    await expect(fileLabelSavePreferenceStore.get()).resolves.toBe(false);
  });

  it("writes the preference to its own capture-preferences file", async () => {
    await fileLabelSavePreferenceStore.set(true);
    expect(Object.keys(mockFiles)).toEqual([FILE_NAME]);
  });

  it("round-trips an opt-in so the choice sticks across launches", async () => {
    await fileLabelSavePreferenceStore.set(true);
    await expect(fileLabelSavePreferenceStore.get()).resolves.toBe(true);
  });

  it("round-trips an opt-out", async () => {
    await fileLabelSavePreferenceStore.set(true);
    await fileLabelSavePreferenceStore.set(false);
    await expect(fileLabelSavePreferenceStore.get()).resolves.toBe(false);
  });

  it("preserves unrelated stored keys when writing", async () => {
    mockFiles[FILE_NAME] = JSON.stringify({ somethingElse: "keep me" });
    await fileLabelSavePreferenceStore.set(true);
    expect(JSON.parse(mockFiles[FILE_NAME])).toEqual({
      somethingElse: "keep me",
      saveLabelPhotos: true,
    });
  });

  it("fails closed on a corrupt file rather than assuming retention", async () => {
    mockFiles[FILE_NAME] = "{not json";
    await expect(fileLabelSavePreferenceStore.get()).resolves.toBe(false);
  });

  it("only a literal true enables retention", async () => {
    for (const stored of ["true", 1, null, {}, undefined]) {
      mockFiles[FILE_NAME] = JSON.stringify({ saveLabelPhotos: stored });
      await expect(fileLabelSavePreferenceStore.get()).resolves.toBe(false);
    }
  });
});
