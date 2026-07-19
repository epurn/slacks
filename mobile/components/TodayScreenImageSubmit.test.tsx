/**
 * Tests for the Today composer's unified text+image submission (FTY-383).
 *
 * Drives the real Today screen: the attach affordance is mounted and reachable;
 * picking a photo shows a thumbnail with a working remove control; submitting
 * text + image posts ONE multipart create, clears the composer (text +
 * thumbnails), and shows the entry immediately as a pending row in place; a
 * text-only submit still takes the JSON path (multipart untouched); and a failed
 * image submit restores the thumbnails so the capture is never lost.
 */

import { act } from "react-test-renderer";

import { TodayScreen } from "./TodayScreen";
import {
  LogEventApiError,
  type LogEventDTO,
  type SubmissionImage,
} from "@/api/logEvents";
import type { ComposerImage, ComposerImagePickers } from "@/components/today/useComposerImages";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

import {
  INACTIVE,
  SESSION,
  cleanupTrees,
  emptyClarification,
  event,
  hasA11yLabel,
  inputValue,
  mount,
  press,
  textContent,
  typeInto,
} from "./today/todayTestUtils";

jest.mock("@/theme/haptics", () => ({
  entryResolvedHaptic: jest.fn(),
  correctionSavedHaptic: jest.fn(),
  targetReachedHaptic: jest.fn(),
}));

// The composer image hook's defaults reach expo-image-picker; every test injects
// picker seams, so the module is never exercised. Stub it out.
jest.mock("expo-image-picker", () => ({}));

jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactNative = require("react-native");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  return {
    SymbolView: ({ name, accessibilityLabel }: { name: string; accessibilityLabel?: string }) =>
      ReactLib.createElement(ReactNative.View, {
        testID: `sf-symbol-${String(name)}`,
        accessibilityLabel,
      }),
  };
});

// Keep the by-date feed hermetic (empty) unless a test overrides `loadEntries`.
jest.mock("@/api/logEvents", () => {
  const actual = jest.requireActual("@/api/logEvents");
  return {
    ...actual,
    listTodayLogEventEntries: jest.fn().mockResolvedValue([]),
  };
});

beforeEach(() => mockReduceMotion(false));
afterEach(cleanupTrees);

const FIXTURE_IMAGE: ComposerImage = {
  uri: "file:///bar.jpg",
  name: "bar.jpg",
  type: "image/jpeg",
  size: 2048,
};

/** Picker seams that return one fixture image via the library, no OS chooser. */
function libraryPickers(image = FIXTURE_IMAGE): Partial<ComposerImagePickers> {
  return {
    presentSourceChooser: jest.fn().mockResolvedValue("library"),
    pickFromLibrary: jest.fn().mockResolvedValue([image]),
  };
}

describe("TodayScreen composer image attachment", () => {
  it("mounts a reachable attach action on the real Today screen", async () => {
    const tree = mount(
      <TodayScreen session={SESSION} load={jest.fn().mockResolvedValue([])} useActive={INACTIVE} />,
    );
    await act(async () => {});
    expect(hasA11yLabel(tree, "Attach photo")).toBe(true);
  });

  it("adds a thumbnail with a working remove control when a photo is picked", async () => {
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={jest.fn().mockResolvedValue([])}
        useActive={INACTIVE}
        composerImagePickers={libraryPickers()}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "Attach photo");
    });
    expect(hasA11yLabel(tree, "Attached photo 1")).toBe(true);
    expect(hasA11yLabel(tree, "Remove photo 1")).toBe(true);

    // Remove drops the thumbnail in place.
    act(() => {
      press(tree, "Remove photo 1");
    });
    expect(hasA11yLabel(tree, "Attached photo 1")).toBe(false);
  });

  it("submits text + image as one multipart create and shows a pending row in place", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const create = jest.fn();
    let resolveCreate!: (dto: LogEventDTO) => void;
    const createWithImages = jest.fn().mockReturnValue(
      new Promise<LogEventDTO>((resolve) => {
        resolveCreate = resolve;
      }),
    );

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        createWithImages={createWithImages}
        getClarification={emptyClarification()}
        useActive={INACTIVE}
        composerImagePickers={libraryPickers()}
        generateKey={() => "img-key-1"}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "2 of these bars");
    await act(async () => {
      press(tree, "Attach photo");
    });
    expect(hasA11yLabel(tree, "Attached photo 1")).toBe(true);

    await act(async () => {
      press(tree, "Add entry");
    });

    // Exactly one multipart create; the JSON path was NOT used.
    expect(createWithImages).toHaveBeenCalledTimes(1);
    expect(create).not.toHaveBeenCalled();
    const [, rawText, images, save, key] = createWithImages.mock.calls[0] as [
      unknown,
      string,
      readonly SubmissionImage[],
      boolean,
      string,
    ];
    expect(rawText).toBe("2 of these bars");
    expect(images).toHaveLength(1);
    expect(images[0]).toMatchObject({ uri: "file:///bar.jpg", type: "image/jpeg" });
    expect(save).toBe(false); // discard-by-default retention
    expect(key).toBe("img-key-1");

    // Immediate acknowledgement: a pending skeleton row appears (not the raw
    // text), the composer text cleared, and the thumbnail cleared — all in place.
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
    expect(inputValue(tree, "Log food or exercise")).toBe("");
    expect(hasA11yLabel(tree, "Attached photo 1")).toBe(false);

    // Reconcile with the server event — still one pending row, no duplicate.
    await act(async () => {
      resolveCreate(event({ id: "server-img-1", raw_text: "2 of these bars", status: "pending" }));
    });
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
  });

  it("submits image-only (no text) with a Photo log marker via the multipart path", async () => {
    const createWithImages = jest
      .fn()
      .mockResolvedValue(event({ id: "server-img-2", raw_text: "Photo log", status: "pending" }));
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={jest.fn().mockResolvedValue([])}
        createWithImages={createWithImages}
        getClarification={emptyClarification()}
        useActive={INACTIVE}
        composerImagePickers={libraryPickers()}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "Attach photo");
    });
    // No text typed — Add is still enabled because a photo is attached.
    await act(async () => {
      press(tree, "Add entry");
    });

    expect(createWithImages).toHaveBeenCalledTimes(1);
    const [, rawText] = createWithImages.mock.calls[0] as [unknown, string];
    expect(rawText).toBe("");
  });

  it("keeps text-only submit on the JSON path (multipart untouched)", async () => {
    const create = jest
      .fn()
      .mockResolvedValue(event({ id: "server-text-1", raw_text: "black coffee", status: "pending" }));
    const createWithImages = jest.fn();
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={jest.fn().mockResolvedValue([])}
        create={create}
        createWithImages={createWithImages}
        getClarification={emptyClarification()}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "black coffee");
    await act(async () => {
      press(tree, "Add entry");
    });

    expect(create).toHaveBeenCalledTimes(1);
    expect(createWithImages).not.toHaveBeenCalled();
  });

  it("restores the thumbnail and surfaces an error when the image submit fails", async () => {
    const createWithImages = jest
      .fn()
      .mockRejectedValue(new LogEventApiError(413, "That photo is too large to upload."));
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={jest.fn().mockResolvedValue([])}
        createWithImages={createWithImages}
        getClarification={emptyClarification()}
        useActive={INACTIVE}
        composerImagePickers={libraryPickers()}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "2 of these bars");
    await act(async () => {
      press(tree, "Attach photo");
    });

    await act(async () => {
      press(tree, "Add entry");
    });

    // The capture is never lost: the thumbnail is restored and the composer text
    // is back, with the error surfaced for a one-tap retry.
    expect(hasA11yLabel(tree, "Attached photo 1")).toBe(true);
    expect(inputValue(tree, "Log food or exercise")).toBe("2 of these bars");
    expect(textContent(tree)).toContain("That photo is too large to upload.");
  });
});
