/**
 * Tests for the Today composer image-attachment hook (FTY-383).
 *
 * Covers the attach interaction end-to-end against injected picker seams: the
 * chooser → library/camera branch, the first-line client-side guard (count /
 * size / type mirroring `labelCapture.ts`), the camera-permission denial and
 * cancel paths, and remove/clear/restore — all with calm, content-free errors.
 */

import { act, create, type ReactTestRenderer } from "react-test-renderer";

import {
  useComposerImages,
  MAX_SUBMISSION_IMAGES,
  MAX_UPLOAD_BYTES,
  type ComposerImage,
  type ComposerImagePickers,
  type UseComposerImages,
} from "./useComposerImages";

// The hook's defaults reach `expo-image-picker`; every test injects seams, so
// stub the module to a bare object (nothing here is exercised).
jest.mock("expo-image-picker", () => ({}));

function image(overrides: Partial<ComposerImage> = {}): ComposerImage {
  return {
    uri: "file:///photo.jpg",
    name: "photo.jpg",
    type: "image/jpeg",
    size: 1000,
    ...overrides,
  };
}

/** Render the hook and expose its latest return value for assertions. */
function renderHook(pickers: Partial<ComposerImagePickers>): {
  captured: { value: UseComposerImages };
  renderer: ReactTestRenderer;
} {
  const captured: { value: UseComposerImages } = { value: null as never };
  function Harness() {
    captured.value = useComposerImages(pickers);
    return null;
  }
  let renderer!: ReactTestRenderer;
  act(() => {
    renderer = create(<Harness />);
  });
  return { captured, renderer };
}

describe("useComposerImages", () => {
  it("attaches a library-picked image via the chooser", async () => {
    const { captured } = renderHook({
      presentSourceChooser: jest.fn().mockResolvedValue("library"),
      pickFromLibrary: jest.fn().mockResolvedValue([image({ uri: "file:///a.jpg" })]),
    });

    await act(async () => {
      await captured.value.attach();
    });

    expect(captured.value.images).toHaveLength(1);
    expect(captured.value.images[0].uri).toBe("file:///a.jpg");
    expect(captured.value.attachError).toBeNull();
  });

  it("captures from the camera after a granted permission", async () => {
    const requestCameraPermission = jest.fn().mockResolvedValue(true);
    const captureFromCamera = jest.fn().mockResolvedValue(image({ uri: "file:///cam.jpg" }));
    const { captured } = renderHook({
      presentSourceChooser: jest.fn().mockResolvedValue("camera"),
      requestCameraPermission,
      captureFromCamera,
    });

    await act(async () => {
      await captured.value.attach();
    });

    expect(requestCameraPermission).toHaveBeenCalled();
    expect(captureFromCamera).toHaveBeenCalled();
    expect(captured.value.images).toHaveLength(1);
  });

  it("surfaces a calm, non-blocking message when camera permission is denied", async () => {
    const captureFromCamera = jest.fn();
    const { captured } = renderHook({
      presentSourceChooser: jest.fn().mockResolvedValue("camera"),
      requestCameraPermission: jest.fn().mockResolvedValue(false),
      captureFromCamera,
    });

    await act(async () => {
      await captured.value.attach();
    });

    expect(captureFromCamera).not.toHaveBeenCalled();
    expect(captured.value.images).toHaveLength(0);
    expect(captured.value.attachError).toMatch(/camera access is off/i);
  });

  it("does nothing when the chooser is cancelled", async () => {
    const { captured } = renderHook({
      presentSourceChooser: jest.fn().mockResolvedValue(null),
      pickFromLibrary: jest.fn(),
    });

    await act(async () => {
      await captured.value.attach();
    });

    expect(captured.value.images).toHaveLength(0);
    expect(captured.value.attachError).toBeNull();
  });

  it("does nothing when the picker is cancelled (null result)", async () => {
    const { captured } = renderHook({
      presentSourceChooser: jest.fn().mockResolvedValue("library"),
      pickFromLibrary: jest.fn().mockResolvedValue(null),
    });

    await act(async () => {
      await captured.value.attach();
    });

    expect(captured.value.images).toHaveLength(0);
    expect(captured.value.attachError).toBeNull();
  });

  it("blocks an oversize image with a calm message (guard, no attach)", async () => {
    const { captured } = renderHook({
      presentSourceChooser: jest.fn().mockResolvedValue("library"),
      pickFromLibrary: jest
        .fn()
        .mockResolvedValue([image({ size: MAX_UPLOAD_BYTES + 1 })]),
    });

    await act(async () => {
      await captured.value.attach();
    });

    expect(captured.value.images).toHaveLength(0);
    expect(captured.value.attachError).toMatch(/too large/i);
  });

  it("blocks a wrong-type file with a calm message (guard, no attach)", async () => {
    const { captured } = renderHook({
      presentSourceChooser: jest.fn().mockResolvedValue("library"),
      pickFromLibrary: jest
        .fn()
        .mockResolvedValue([image({ type: "application/pdf" })]),
    });

    await act(async () => {
      await captured.value.attach();
    });

    expect(captured.value.images).toHaveLength(0);
    expect(captured.value.attachError).not.toBeNull();
  });

  it("caps attachments at MAX_SUBMISSION_IMAGES and messages the limit", async () => {
    const many = Array.from({ length: MAX_SUBMISSION_IMAGES + 2 }, (_, i) =>
      image({ uri: `file:///${i}.jpg` }),
    );
    const { captured } = renderHook({
      presentSourceChooser: jest.fn().mockResolvedValue("library"),
      pickFromLibrary: jest.fn().mockResolvedValue(many),
    });

    await act(async () => {
      await captured.value.attach();
    });

    expect(captured.value.images).toHaveLength(MAX_SUBMISSION_IMAGES);
    expect(captured.value.attachError).toMatch(new RegExp(`up to ${MAX_SUBMISSION_IMAGES}`));
  });

  it("prefers the specific size/type message over the count message when a batch trips both", async () => {
    // A single multi-select batch that both contains an oversize image AND
    // pushes past the 4-photo ceiling. The specific size reason is the more
    // useful one to surface, so the generic count message must not clobber it.
    const batch = [
      image({ uri: "file:///0.jpg" }),
      image({ uri: "file:///big.jpg", size: MAX_UPLOAD_BYTES + 1 }),
      image({ uri: "file:///1.jpg" }),
      image({ uri: "file:///2.jpg" }),
      image({ uri: "file:///3.jpg" }),
      image({ uri: "file:///4.jpg" }),
    ];
    const { captured } = renderHook({
      presentSourceChooser: jest.fn().mockResolvedValue("library"),
      pickFromLibrary: jest.fn().mockResolvedValue(batch),
    });

    await act(async () => {
      await captured.value.attach();
    });

    expect(captured.value.images).toHaveLength(MAX_SUBMISSION_IMAGES);
    expect(captured.value.attachError).toMatch(/too large/i);
    expect(captured.value.attachError).not.toMatch(new RegExp(`up to ${MAX_SUBMISSION_IMAGES}`));
  });

  it("refuses to attach once already at the limit", async () => {
    const pick = jest
      .fn()
      .mockResolvedValueOnce(
        Array.from({ length: MAX_SUBMISSION_IMAGES }, (_, i) => image({ uri: `file:///${i}.jpg` })),
      )
      .mockResolvedValueOnce([image({ uri: "file:///extra.jpg" })]);
    const { captured } = renderHook({
      presentSourceChooser: jest.fn().mockResolvedValue("library"),
      pickFromLibrary: pick,
    });

    await act(async () => {
      await captured.value.attach();
    });
    await act(async () => {
      await captured.value.attach();
    });

    expect(captured.value.images).toHaveLength(MAX_SUBMISSION_IMAGES);
    expect(captured.value.attachError).toMatch(new RegExp(`up to ${MAX_SUBMISSION_IMAGES}`));
  });

  it("surfaces a content-free error when the picker throws", async () => {
    const sensitiveUri = "file:///private/secret.jpg";
    const { captured } = renderHook({
      presentSourceChooser: jest.fn().mockResolvedValue("library"),
      pickFromLibrary: jest.fn().mockRejectedValue(new Error(sensitiveUri)),
    });

    await act(async () => {
      await captured.value.attach();
    });

    expect(captured.value.images).toHaveLength(0);
    expect(captured.value.attachError).not.toBeNull();
    expect(captured.value.attachError).not.toContain(sensitiveUri);
  });

  it("removes and clears attachments", async () => {
    const { captured } = renderHook({
      presentSourceChooser: jest.fn().mockResolvedValue("library"),
      pickFromLibrary: jest
        .fn()
        .mockResolvedValue([image({ uri: "file:///a.jpg" }), image({ uri: "file:///b.jpg" })]),
    });

    await act(async () => {
      await captured.value.attach();
    });
    expect(captured.value.images).toHaveLength(2);

    act(() => {
      captured.value.removeImage(0);
    });
    expect(captured.value.images).toHaveLength(1);
    expect(captured.value.images[0].uri).toBe("file:///b.jpg");

    act(() => {
      captured.value.clearImages();
    });
    expect(captured.value.images).toHaveLength(0);
  });
});
