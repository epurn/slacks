/**
 * Tests for LabelCaptureScreen (FTY-064, generalized in FTY-311, two-tap flow in
 * FTY-433).
 *
 * Covers:
 * - Permission flows: rationale shown, blocked → Open Settings, granted → camera.
 * - Merged shutter → upload (FTY-433): the shutter submits directly, with no
 *   Upload button, no blocking preview, and no per-capture save question.
 * - Retake during the upload: back to the camera, and the superseded capture's
 *   outcome (success or failure) never surfaces.
 * - Capture chrome (framing guide, flash) and its phase gating.
 * - Submit path: onSubmit receives the captured image URI + save-photo flag; the
 *   capture component makes no assumption that a LogEventDTO comes back.
 * - Normal Today host: onSubmit uploads via a label upload and forwards the
 *   returned event to the confirm-parsed flow (host wiring unchanged).
 * - Exact-evidence host: onSubmit receives the capture (URI + save flag) without
 *   creating a log event.
 * - The sticky save preference (FTY-433): default off, `save=false` on the real
 *   upload request, deliberate opt-in sends `save=true`, and a stored opt-in is
 *   visible on the control the next time capture opens.
 * - Submit failure: in-place error, no image bytes/URI/extracted content leaked.
 * - Client-side size/type guard (pure unit).
 */

import React from "react";
import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { PermissionStatus } from "expo";
import type { PermissionResponse } from "expo";

import { LabelCaptureScreen, type LabelCapture } from "./LabelCaptureScreen";
import {
  uploadLabelImage,
  validateImageGuard,
  MAX_UPLOAD_BYTES,
  LabelUploadTooLargeError,
  LabelUploadInvalidTypeError,
  LabelUploadApiError,
  type LocalImageFile,
  type OpenLocalImage,
} from "@/api/labelCapture";
import type { LogEventDTO } from "@/api/logEvents";
import type { ApiSession } from "@/state/session";
import type { LabelSavePreferenceStore } from "@/state/labelSavePreference";

// ─── Mocks ───────────────────────────────────────────────────────────────────

jest.mock("expo-camera", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require("react");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require("react-native");
  return {
    // Forwards props (notably `enableTorch`) onto the stub so tests can assert
    // the flash toggle is actually wired to the CameraView.
    CameraView: jest.fn().mockImplementation((props: Record<string, unknown>) =>
      React.createElement(View, { ...props, testID: "camera-view" }),
    ),
  };
});

jest.mock("expo-linking", () => ({
  openSettings: jest.fn().mockResolvedValue(undefined),
}));

// expo-symbols is a native module — stub SymbolView so the flash toggle icon
// renders (same pattern as ConfirmParsedValuesSheet.test.tsx / AppIcon.test.tsx).
jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require("react");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require("react-native");
  return {
    SymbolView: ({
      name,
      accessibilityLabel,
    }: {
      name: string;
      accessibilityLabel?: string;
    }) =>
      React.createElement(View, {
        testID: `sf-symbol-${String(name)}`,
        accessibilityLabel,
      }),
  };
});

// ─── Helpers ─────────────────────────────────────────────────────────────────

const USER_ID = "11111111-1111-1111-1111-111111111111";

/** A resolving submit handler — the default for tests that don't inspect it. */
function noopSubmit(): jest.Mock<Promise<void>, [LabelCapture]> {
  return jest.fn<Promise<void>, [LabelCapture]>().mockResolvedValue(undefined);
}

function makeEvent(overrides: Partial<LogEventDTO> = {}): LogEventDTO {
  return {
    id: "label-event-1",
    user_id: USER_ID,
    raw_text: "nutrition label photo",
    name: null,
    status: "pending",
    created_at: "2026-06-27T10:00:00Z",
    updated_at: "2026-06-27T10:00:00Z",
    ...overrides,
  };
}

function makePermission(overrides: Partial<PermissionResponse>): PermissionResponse {
  return {
    status: PermissionStatus.UNDETERMINED,
    granted: false,
    canAskAgain: true,
    expires: "never",
    ...overrides,
  };
}

function makeGrantedHook(): () => [PermissionResponse, () => Promise<PermissionResponse>, () => Promise<PermissionResponse>] {
  const granted = makePermission({ status: PermissionStatus.GRANTED, granted: true, canAskAgain: false });
  return () => [
    granted,
    jest.fn().mockResolvedValue(granted),
    jest.fn().mockResolvedValue(granted),
  ];
}

function makeDeniedHook(canAskAgain = false): () => [PermissionResponse, () => Promise<PermissionResponse>, () => Promise<PermissionResponse>] {
  const denied = makePermission({ status: PermissionStatus.DENIED, granted: false, canAskAgain });
  return () => [
    denied,
    jest.fn().mockResolvedValue(denied),
    jest.fn().mockResolvedValue(denied),
  ];
}

const SAFE_AREA_METRICS = {
  frame: { x: 0, y: 0, width: 390, height: 844 },
  insets: { top: 47, left: 0, right: 0, bottom: 34 },
};

function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(
      <SafeAreaProvider initialMetrics={SAFE_AREA_METRICS}>
        {element}
      </SafeAreaProvider>,
    );
  });
  return tree;
}

function textContent(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

function hasA11yLabel(tree: ReactTestRenderer, label: string): boolean {
  return tree.root.findAll((n) => n.props.accessibilityLabel === label).length > 0;
}

function press(tree: ReactTestRenderer, label: string): void {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
  act(() => {
    node.props.onPress();
  });
}

/** Flush pending microtasks (the preference hydrate, an upload settle). */
async function flush(): Promise<void> {
  await act(async () => {});
}

/**
 * Tap the shutter (FTY-433: this both captures *and* starts the upload) and, if
 * asked, deliberately turn the sticky save preference on beforehand — the only
 * way `save=true` can ever be sent.
 */
async function shoot(tree: ReactTestRenderer, save = false): Promise<void> {
  if (save) {
    press(tree, "Save label photos");
  }
  await act(async () => {
    press(tree, "Take photo");
  });
}

/** An in-memory save-preference store: the seam the on-device file store fills. */
function makeSaveStore(initial = false): LabelSavePreferenceStore & {
  readonly stored: () => boolean;
  readonly set: jest.Mock<Promise<void>, [boolean]>;
} {
  let value = initial;
  const set = jest.fn<Promise<void>, [boolean]>(async (next) => {
    value = next;
  });
  return { get: async () => value, set, stored: () => value };
}

const UPLOAD_SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: USER_ID,
};

/**
 * A fake readable local image + its opener seam, so a test can drive the *real*
 * `uploadLabelImage` client and assert the URL the auto-upload actually issues
 * (notably its `?save=` retention flag) without a filesystem or a network.
 */
function fakeUpload(): { openImage: OpenLocalImage; upload: jest.Mock } {
  const upload = jest.fn(() =>
    Promise.resolve({ status: 201, body: JSON.stringify(makeEvent()) }),
  );
  const file: LocalImageFile = {
    exists: true,
    size: 50_000,
    type: "image/jpeg",
    upload,
  };
  return {
    openImage: jest.fn().mockReturnValue(file) as unknown as OpenLocalImage,
    upload,
  };
}

// ─── Client-side guard (pure unit tests) ─────────────────────────────────────

describe("validateImageGuard", () => {
  it("passes for an allowed content type within the size limit", () => {
    expect(() => validateImageGuard(1024, "image/jpeg")).not.toThrow();
    expect(() => validateImageGuard(1024, "image/png")).not.toThrow();
    expect(() => validateImageGuard(1024, "image/webp")).not.toThrow();
  });

  it("throws LabelUploadTooLargeError when size exceeds MAX_UPLOAD_BYTES", () => {
    expect(() =>
      validateImageGuard(MAX_UPLOAD_BYTES + 1, "image/jpeg"),
    ).toThrow(LabelUploadTooLargeError);
  });

  it("passes exactly at the size limit", () => {
    expect(() => validateImageGuard(MAX_UPLOAD_BYTES, "image/jpeg")).not.toThrow();
  });

  it("throws LabelUploadInvalidTypeError for a non-image content type", () => {
    expect(() => validateImageGuard(1024, "application/pdf")).toThrow(
      LabelUploadInvalidTypeError,
    );
    expect(() => validateImageGuard(1024, "text/plain")).toThrow(
      LabelUploadInvalidTypeError,
    );
    expect(() => validateImageGuard(1024, "video/mp4")).toThrow(
      LabelUploadInvalidTypeError,
    );
  });

  it("normalizes content type before checking (strips parameters)", () => {
    expect(() =>
      validateImageGuard(1024, "image/jpeg; charset=utf-8"),
    ).not.toThrow();
  });

  it("rejects an empty content type string", () => {
    expect(() => validateImageGuard(1024, "")).toThrow(LabelUploadInvalidTypeError);
  });

  it("error messages do not contain image bytes or sensitive content", () => {
    try {
      validateImageGuard(MAX_UPLOAD_BYTES + 1, "image/jpeg");
    } catch (err) {
      const msg = (err as LabelUploadTooLargeError).message;
      expect(msg).not.toMatch(/byte|data:|file:|content/i);
    }

    try {
      validateImageGuard(100, "application/octet-stream");
    } catch (err) {
      const msg = (err as LabelUploadInvalidTypeError).message;
      expect(msg).not.toMatch(/byte|data:|file:/i);
    }
  });
});

// ─── Permission flow ──────────────────────────────────────────────────────────

describe("LabelCaptureScreen – permission flows", () => {
  it("shows the label-specific rationale when permission is undetermined", () => {
    const undetermined = makePermission({ status: PermissionStatus.UNDETERMINED });
    const hook = () => [
      undetermined,
      jest.fn().mockResolvedValue(undetermined),
      jest.fn().mockResolvedValue(undetermined),
    ] as [PermissionResponse, () => Promise<PermissionResponse>, () => Promise<PermissionResponse>];
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={noopSubmit()}
        onClose={jest.fn()}
        permissionsHook={hook}
      />,
    );
    // Rationale mentions the label-capture purpose (not just a generic camera message).
    const content = textContent(tree);
    expect(content).toContain("nutrition label");
    expect(hasA11yLabel(tree, "Allow camera access")).toBe(true);
  });

  it("gracefully handles permanently blocked permission with an Open Settings path", () => {
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={noopSubmit()}
        onClose={jest.fn()}
        permissionsHook={makeDeniedHook(false)}
      />,
    );
    expect(hasA11yLabel(tree, "Open Settings")).toBe(true);
    // Close is always available so there is never a dead end.
    expect(hasA11yLabel(tree, "Close scanner")).toBe(true);
  });

  it("shows the camera viewfinder and shutter when permission is granted", () => {
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={noopSubmit()}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
      />,
    );
    expect(hasA11yLabel(tree, "Camera viewfinder")).toBe(true);
    expect(hasA11yLabel(tree, "Take photo")).toBe(true);
  });

  it("calls onClose when the close button is pressed before permission is granted", () => {
    const onClose = jest.fn();
    const undetermined = makePermission({ status: PermissionStatus.UNDETERMINED });
    const hook = () => [
      undetermined,
      jest.fn().mockResolvedValue(undetermined),
      jest.fn().mockResolvedValue(undetermined),
    ] as [PermissionResponse, () => Promise<PermissionResponse>, () => Promise<PermissionResponse>];
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={noopSubmit()}
        onClose={onClose}
        permissionsHook={hook}
      />,
    );
    press(tree, "Close scanner");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

// ─── Merged shutter → upload (FTY-433) ───────────────────────────────────────

describe("LabelCaptureScreen – shutter auto-uploads", () => {
  /** A submit that stays in flight until the test resolves/rejects it. */
  function pendingSubmit(): {
    onSubmit: jest.Mock<Promise<void>, [LabelCapture]>;
    capture: () => LabelCapture;
    resolve: () => void;
    reject: (error: unknown) => void;
  } {
    let resolveSubmit!: () => void;
    let rejectSubmit!: (error: unknown) => void;
    const onSubmit = jest.fn<Promise<void>, [LabelCapture]>(
      () =>
        new Promise<void>((res, rej) => {
          resolveSubmit = res;
          rejectSubmit = rej;
        }),
    );
    return {
      onSubmit,
      capture: () => onSubmit.mock.calls[0][0],
      resolve: () => resolveSubmit(),
      reject: (error) => rejectSubmit(error),
    };
  }

  function mountWithPending(pending: ReturnType<typeof pendingSubmit>) {
    return mount(
      <LabelCaptureScreen
        onSubmit={pending.onSubmit}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: "file:///label.jpg" })}
        savePreferenceStore={makeSaveStore()}
      />,
    );
  }

  it("uploads straight from the shutter — no Upload button, no preview, no save question", async () => {
    const pending = pendingSubmit();
    const tree = mountWithPending(pending);
    await flush();

    await shoot(tree);

    // The capture was submitted by the shutter itself.
    expect(pending.onSubmit).toHaveBeenCalledTimes(1);
    expect(pending.capture()).toMatchObject({
      imageUri: "file:///label.jpg",
      savePhoto: false,
    });
    // The blocking preview stop is gone: no Upload button and no per-capture
    // save question anywhere in the tree.
    expect(hasA11yLabel(tree, "Upload label")).toBe(false);
    expect(hasA11yLabel(tree, "Save this photo")).toBe(false);
    // The uploading state is what the user sees, with the captured frame held
    // behind it and Retake still available.
    expect(hasA11yLabel(tree, "Uploading label")).toBe(true);
    expect(hasA11yLabel(tree, "Captured nutrition label photo")).toBe(true);
    expect(hasA11yLabel(tree, "Retake photo")).toBe(true);

    await act(async () => {
      pending.resolve();
    });
  });

  it("retake during the upload returns to the camera and aborts the capture", async () => {
    const pending = pendingSubmit();
    const tree = mountWithPending(pending);
    await flush();

    await shoot(tree);
    expect(pending.capture().signal.aborted).toBe(false);

    press(tree, "Retake photo");

    // Back at the viewfinder, and the in-flight capture is superseded so a host
    // that honours the signal drops its result.
    expect(hasA11yLabel(tree, "Take photo")).toBe(true);
    expect(hasA11yLabel(tree, "Uploading label")).toBe(false);
    expect(pending.capture().signal.aborted).toBe(true);

    // The superseded upload settling later must not disturb the camera phase.
    await act(async () => {
      pending.resolve();
    });
    expect(hasA11yLabel(tree, "Take photo")).toBe(true);
    expect(hasA11yLabel(tree, "Uploading label")).toBe(false);
  });

  it("a superseded upload's failure never surfaces as an error", async () => {
    const pending = pendingSubmit();
    const tree = mountWithPending(pending);
    await flush();

    await shoot(tree);
    press(tree, "Retake photo");

    await act(async () => {
      pending.reject(new LabelUploadApiError(500, "We couldn't upload the label."));
    });

    // The user already moved on: no error copy, still framing the next shot.
    expect(textContent(tree)).not.toContain("couldn't upload");
    expect(hasA11yLabel(tree, "Take photo")).toBe(true);
  });

  it("a second shutter after a retake submits the new capture", async () => {
    const onSubmit = noopSubmit();
    const takePhoto = jest
      .fn()
      .mockResolvedValueOnce({ uri: "file:///first.jpg" })
      .mockResolvedValueOnce({ uri: "file:///second.jpg" });
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={onSubmit}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={takePhoto}
        savePreferenceStore={makeSaveStore()}
      />,
    );
    await flush();

    await shoot(tree);
    press(tree, "Retake photo");
    await shoot(tree);

    expect(onSubmit).toHaveBeenCalledTimes(2);
    expect(onSubmit.mock.calls[1][0]).toMatchObject({
      imageUri: "file:///second.jpg",
    });
  });
});

// ─── Capture chrome (framing guide, hint, flash) ─────────────────────────────

describe("LabelCaptureScreen – capture chrome", () => {
  it("shows the framing guide hint and a flash toggle in the camera phase", () => {
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={noopSubmit()}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
      />,
    );

    expect(hasA11yLabel(tree, "Fit the nutrition label inside the frame")).toBe(true);
    expect(hasA11yLabel(tree, "Flash")).toBe(true);
  });

  it("flash is off by default and toggles enableTorch + accessibility state on tap", () => {
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={noopSubmit()}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
      />,
    );

    const camera = () => tree.root.find((n) => n.props.testID === "camera-view");
    const flashButton = () =>
      tree.root.find(
        (n) => n.props.accessibilityLabel === "Flash" && typeof n.props.onPress === "function",
      );

    expect(camera().props.enableTorch).toBe(false);
    expect(flashButton().props.accessibilityState).toEqual({ selected: false });

    act(() => {
      flashButton().props.onPress();
    });

    expect(camera().props.enableTorch).toBe(true);
    expect(flashButton().props.accessibilityState).toEqual({ selected: true });
  });

  it("hides the framing guide, flash, and save toggle once uploading", async () => {
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={noopSubmit()}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: "file:///captured-label.jpg" })}
        savePreferenceStore={makeSaveStore()}
      />,
    );

    await shoot(tree);

    expect(hasA11yLabel(tree, "Fit the nutrition label inside the frame")).toBe(false);
    expect(hasA11yLabel(tree, "Flash")).toBe(false);
    expect(hasA11yLabel(tree, "Save label photos")).toBe(false);
  });

  it("turns the torch off when leaving the camera phase even if flash was on", async () => {
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={noopSubmit()}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: "file:///captured-label.jpg" })}
        savePreferenceStore={makeSaveStore()}
      />,
    );

    const camera = () => tree.root.find((n) => n.props.testID === "camera-view");
    const flashButton = () =>
      tree.root.find(
        (n) => n.props.accessibilityLabel === "Flash" && typeof n.props.onPress === "function",
      );

    // Turn the flash on while framing.
    act(() => {
      flashButton().props.onPress();
    });
    expect(camera().props.enableTorch).toBe(true);

    // Take the photo → preview. The flash control is hidden, so the torch must
    // not stay lit while the CameraView is still mounted.
    await act(async () => {
      press(tree, "Take photo");
    });
    expect(camera().props.enableTorch).toBe(false);

    // Returning to framing re-lights the torch (the toggle state is retained).
    press(tree, "Retake photo");
    expect(camera().props.enableTorch).toBe(true);
  });
});

// ─── Submit flow (generic) ───────────────────────────────────────────────────

describe("LabelCaptureScreen – submit", () => {
  it("calls onSubmit with the captured image URI and save-photo off by default", async () => {
    const onSubmit = noopSubmit();
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={onSubmit}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: "file:///label.jpg" })}
        savePreferenceStore={makeSaveStore()}
      />,
    );
    await flush();

    await shoot(tree);

    expect(onSubmit).toHaveBeenCalledTimes(1);
    // The capture carries the URI and the save flag — no LogEventDTO required.
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      imageUri: "file:///label.jpg",
      savePhoto: false,
    });
  });

  it("forwards savePhoto=true only when the sticky save preference is on", async () => {
    const onSubmit = noopSubmit();
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={onSubmit}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: "file:///label.jpg" })}
        savePreferenceStore={makeSaveStore()}
      />,
    );
    await flush();

    await shoot(tree, /* save */ true);

    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      imageUri: "file:///label.jpg",
      savePhoto: true,
    });
  });

  it("normal Today host: onSubmit uploads and forwards the returned event (path unchanged)", async () => {
    // Models the TodayScreen wiring: onSubmit uploads the label then hands the
    // returned LogEventDTO to the confirm-parsed flow.
    const createdEvent = makeEvent({ id: "label-server-1" });
    const upload = jest.fn().mockResolvedValue(createdEvent);
    const onUploaded = jest.fn();
    const onSubmit = jest
      .fn<Promise<void>, [LabelCapture]>()
      .mockImplementation(async ({ imageUri, savePhoto }) => {
        const event = await upload(imageUri, savePhoto);
        onUploaded(event);
      });

    const tree = mount(
      <LabelCaptureScreen
        onSubmit={onSubmit}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: "file:///label.jpg" })}
        savePreferenceStore={makeSaveStore()}
      />,
    );
    await flush();

    await shoot(tree);

    expect(upload).toHaveBeenCalledWith("file:///label.jpg", false);
    expect(onUploaded).toHaveBeenCalledTimes(1);
    expect(onUploaded).toHaveBeenCalledWith(createdEvent);
  });

  it("exact-evidence host: onSubmit receives the capture without creating a log event", async () => {
    // The exact-evidence host (FTY-312) just keeps the URI + save flag; it does
    // not upload or produce a LogEventDTO.
    const received: LabelCapture[] = [];
    const onSubmit = jest
      .fn<Promise<void>, [LabelCapture]>()
      .mockImplementation(async (capture) => {
        received.push(capture);
      });

    const tree = mount(
      <LabelCaptureScreen
        onSubmit={onSubmit}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: "file:///exact-label.jpg" })}
        savePreferenceStore={makeSaveStore()}
      />,
    );
    await flush();

    await shoot(tree, /* save */ true);

    expect(received).toHaveLength(1);
    expect(received[0]).toMatchObject({
      imageUri: "file:///exact-label.jpg",
      savePhoto: true,
    });
  });

  it("shows an in-place error when onSubmit rejects, without leaking sensitive content", async () => {
    const onSubmit = jest
      .fn<Promise<void>, [LabelCapture]>()
      .mockRejectedValue(new LabelUploadApiError(500, "We couldn't upload the label (status 500)."));
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={onSubmit}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: "file:///label.jpg" })}
        savePreferenceStore={makeSaveStore()}
      />,
    );
    await flush();

    await shoot(tree);

    // Error is shown; the message must not contain image bytes or sensitive content.
    const content = textContent(tree);
    expect(content).toContain("couldn't upload");
    expect(content).not.toMatch(/file:|data:|base64/);
  });

  it("submit failure does not echo the image URI or bytes", async () => {
    const sensitiveUri = "file:///private/user/captured-private.jpg";
    const onSubmit = jest
      .fn<Promise<void>, [LabelCapture]>()
      .mockRejectedValue(new LabelUploadApiError(500, "We couldn't upload the label (status 500)."));
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={onSubmit}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: sensitiveUri })}
        savePreferenceStore={makeSaveStore()}
      />,
    );
    await flush();

    await shoot(tree);

    const content = textContent(tree);
    // Error message must not contain the image URI or any path-like content.
    expect(content).not.toContain(sensitiveUri);
    expect(content).not.toContain("private");
    expect(content).not.toContain("captured-private");
  });

  it("shows the loading indicator while onSubmit is in flight", async () => {
    let resolveSubmit!: () => void;
    const onSubmit = jest.fn<Promise<void>, [LabelCapture]>().mockReturnValue(
      new Promise<void>((resolve) => {
        resolveSubmit = resolve;
      }),
    );
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={onSubmit}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: "file:///label.jpg" })}
        savePreferenceStore={makeSaveStore()}
      />,
    );
    await flush();

    await shoot(tree);

    // While submit is in flight, a spinner is shown over the held capture and
    // the shutter is gone.
    expect(hasA11yLabel(tree, "Uploading label")).toBe(true);
    expect(hasA11yLabel(tree, "Take photo")).toBe(false);

    await act(async () => {
      resolveSubmit();
    });
  });
});

// ─── Sticky save preference (FTY-433) ────────────────────────────────────────

describe("LabelCaptureScreen – sticky save preference", () => {
  function mountWithStore(
    store: LabelSavePreferenceStore,
    onSubmit = noopSubmit(),
  ): ReactTestRenderer {
    return mount(
      <LabelCaptureScreen
        onSubmit={onSubmit}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: "file:///label.jpg" })}
        savePreferenceStore={store}
      />,
    );
  }

  function saveToggle(tree: ReactTestRenderer) {
    return tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Save label photos" &&
        typeof n.props.onPress === "function",
    );
  }

  it("is off by default, in the camera chrome rather than on the capture path", async () => {
    const tree = mountWithStore(makeSaveStore());
    await flush();

    expect(saveToggle(tree).props.accessibilityState).toEqual({
      selected: false,
    });
    // Off is the quiet resting state — no "saving" caption to read.
    expect(textContent(tree)).not.toContain("Saving photos");
  });

  it("the auto-upload request carries save=false while the preference is off", async () => {
    // Drives the REAL upload client so the assertion is on the request the
    // shutter issues, not just the flag handed to the host.
    const { openImage, upload } = fakeUpload();
    const onSubmit = jest
      .fn<Promise<void>, [LabelCapture]>()
      .mockImplementation(async ({ imageUri, savePhoto }) => {
        await uploadLabelImage(UPLOAD_SESSION, imageUri, savePhoto, openImage);
      });
    const tree = mountWithStore(makeSaveStore(), onSubmit);
    await flush();

    await shoot(tree);

    expect(upload).toHaveBeenCalledTimes(1);
    expect(upload.mock.calls[0][0]).toBe(
      `${UPLOAD_SESSION.baseUrl}/api/users/${USER_ID}/log-events/label?save=false`,
    );
  });

  it("a deliberate opt-in shows the sticky state, persists it, and sends save=true", async () => {
    const store = makeSaveStore();
    const { openImage, upload } = fakeUpload();
    const onSubmit = jest
      .fn<Promise<void>, [LabelCapture]>()
      .mockImplementation(async ({ imageUri, savePhoto }) => {
        await uploadLabelImage(UPLOAD_SESSION, imageUri, savePhoto, openImage);
      });
    const tree = mountWithStore(store, onSubmit);
    await flush();

    act(() => {
      saveToggle(tree).props.onPress();
    });

    // The control itself shows the state it now holds…
    expect(saveToggle(tree).props.accessibilityState).toEqual({
      selected: true,
    });
    expect(textContent(tree)).toContain("Saving photos");
    // …it is written through so it survives the next launch…
    expect(store.set).toHaveBeenCalledWith(true);
    expect(store.stored()).toBe(true);

    await act(async () => {
      press(tree, "Take photo");
    });

    // …and the auto-upload carries the retention flag.
    expect(upload.mock.calls[0][0]).toContain("?save=true");
  });

  it("a stored opt-in is already on when capture reopens, and sends save=true", async () => {
    const { openImage, upload } = fakeUpload();
    const onSubmit = jest
      .fn<Promise<void>, [LabelCapture]>()
      .mockImplementation(async ({ imageUri, savePhoto }) => {
        await uploadLabelImage(UPLOAD_SESSION, imageUri, savePhoto, openImage);
      });
    // A fresh mount over a store that already holds the opt-in — the "next time
    // the user opens label capture" case.
    const tree = mountWithStore(makeSaveStore(true), onSubmit);
    await flush();

    expect(saveToggle(tree).props.accessibilityState).toEqual({
      selected: true,
    });

    await act(async () => {
      press(tree, "Take photo");
    });

    expect(upload.mock.calls[0][0]).toContain("?save=true");
  });

  it("a shutter that beats the preference read still uploads with save=false", async () => {
    // Fail closed (FTY-077): until the stored value is known, discard-by-default
    // wins — an opt-in can never be *assumed*.
    let releaseRead!: (value: boolean) => void;
    const store: LabelSavePreferenceStore = {
      get: () =>
        new Promise<boolean>((resolve) => {
          releaseRead = resolve;
        }),
      set: jest.fn().mockResolvedValue(undefined),
    };
    const onSubmit = noopSubmit();
    const tree = mountWithStore(store, onSubmit);

    await act(async () => {
      press(tree, "Take photo");
    });

    expect(onSubmit.mock.calls[0][0]).toMatchObject({ savePhoto: false });

    await act(async () => {
      releaseRead(true);
    });
  });
});

// ─── Photo-library fallback (FTY-381) ────────────────────────────────────────

describe("LabelCaptureScreen – photo-library fallback", () => {
  it("offers a Choose from Library affordance in the camera phase", () => {
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={noopSubmit()}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
      />,
    );
    expect(hasA11yLabel(tree, "Choose from Library")).toBe(true);
  });

  it("picks a library photo → preview → uploads it via onSubmit (end-to-end path)", async () => {
    const onSubmit = noopSubmit();
    const pickPhoto = jest
      .fn()
      .mockResolvedValue({ uri: "file:///library-label.jpg" });
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={onSubmit}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        pickPhoto={pickPhoto}
      />,
    );

    await act(async () => {
      press(tree, "Choose from Library");
    });

    // The picked photo starts the same auto-upload a capture does.
    expect(hasA11yLabel(tree, "Uploading label")).toBe(true);
    expect(hasA11yLabel(tree, "Take photo")).toBe(false);

    // The picked URI feeds the same submit handler + save semantics as a capture.
    expect(pickPhoto).toHaveBeenCalledTimes(1);
    expect(onSubmit.mock.calls[0][0]).toMatchObject({
      imageUri: "file:///library-label.jpg",
      savePhoto: false,
    });
  });

  it("stays in the camera phase with no error when the picker is canceled", async () => {
    const pickPhoto = jest.fn().mockResolvedValue(null); // user canceled
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={noopSubmit()}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        pickPhoto={pickPhoto}
      />,
    );

    await act(async () => {
      press(tree, "Choose from Library");
    });

    // No upload started, no error — the shutter (camera phase) is still shown.
    expect(hasA11yLabel(tree, "Take photo")).toBe(true);
    expect(hasA11yLabel(tree, "Uploading label")).toBe(false);
    const content = textContent(tree);
    expect(content).not.toContain("Couldn't open your photo library");
  });

  it("surfaces a content-free, actionable error when the picker throws", async () => {
    const pickPhoto = jest
      .fn()
      .mockRejectedValue(new Error("file:///private/secret.jpg failed to open"));
    const tree = mount(
      <LabelCaptureScreen
        onSubmit={noopSubmit()}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        pickPhoto={pickPhoto}
      />,
    );

    await act(async () => {
      press(tree, "Choose from Library");
    });

    const content = textContent(tree);
    expect(content).toContain("Couldn't open your photo library");
    // The rejection's message (which carried a path) must never reach the UI.
    expect(content).not.toContain("secret");
    expect(content).not.toMatch(/file:|data:/);
    // Not a dead end: the user can still retry from the camera surface.
    expect(hasA11yLabel(tree, "Choose from Library")).toBe(true);
  });
});

// ─── Security / sensitivity ───────────────────────────────────────────────────

describe("LabelCaptureScreen – security and sensitivity", () => {
  it("LabelUploadApiError message does not echo request body or image content", () => {
    const err = new LabelUploadApiError(500, "We couldn't upload the label (status 500).");
    expect(err.message).not.toMatch(/byte|base64|data:|image\/|file:/i);
  });

  it("LabelUploadTooLargeError message is nonjudgmental and content-free", () => {
    const err = new LabelUploadTooLargeError();
    expect(err.message).not.toMatch(/byte|data:|base64/i);
    expect(err.message.length).toBeGreaterThan(0);
  });

  it("LabelUploadInvalidTypeError message is nonjudgmental and content-free", () => {
    const err = new LabelUploadInvalidTypeError();
    expect(err.message).not.toMatch(/byte|data:|base64/i);
    expect(err.message.length).toBeGreaterThan(0);
  });
});
