/**
 * Tests for LabelCaptureScreen (FTY-064).
 *
 * Covers:
 * - Happy path: capture → upload → onUploaded called with the pending event.
 * - Save-photo opt-in: toggling save sends save=true to the upload function.
 * - Default: save=false is sent when the toggle is left off.
 * - Retake: user can retake the photo after preview.
 * - Upload failure: error shown, no image bytes or sensitive content in the message.
 * - Permission-denied handling: rationale shown + path back (via CameraCapture).
 * - Client-side size guard: oversized image rejected before any upload call.
 * - Client-side type guard: non-image content type rejected before any upload call.
 * - Errors/logs never contain image bytes, URIs, or extracted content.
 */

import React from "react";
import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { PermissionStatus } from "expo";
import type { PermissionResponse } from "expo";

import { LabelCaptureScreen } from "./LabelCaptureScreen";
import {
  validateImageGuard,
  MAX_UPLOAD_BYTES,
  LabelUploadTooLargeError,
  LabelUploadInvalidTypeError,
  LabelUploadApiError,
} from "@/api/labelCapture";
import type { LogEventDTO } from "@/api/logEvents";
import type { ApiSession } from "@/state/session";

// ─── Mocks ───────────────────────────────────────────────────────────────────

jest.mock("expo-camera", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require("react");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require("react-native");
  return {
    CameraView: jest.fn().mockImplementation(() =>
      React.createElement(View, {
        testID: "camera-view",
        accessibilityLabel: "Camera viewfinder",
      }),
    ),
  };
});

jest.mock("expo-linking", () => ({
  openSettings: jest.fn().mockResolvedValue(undefined),
}));

// ─── Helpers ─────────────────────────────────────────────────────────────────

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

function makeEvent(overrides: Partial<LogEventDTO> = {}): LogEventDTO {
  return {
    id: "label-event-1",
    user_id: SESSION.userId,
    raw_text: "nutrition label photo",
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
        session={SESSION}
        onUploaded={jest.fn()}
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
        session={SESSION}
        onUploaded={jest.fn()}
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
        session={SESSION}
        onUploaded={jest.fn()}
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
        session={SESSION}
        onUploaded={jest.fn()}
        onClose={onClose}
        permissionsHook={hook}
      />,
    );
    press(tree, "Close scanner");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

// ─── Capture → preview ───────────────────────────────────────────────────────

describe("LabelCaptureScreen – capture and preview", () => {
  it("transitions to preview after taking a photo", async () => {
    const fakePhoto = { uri: "file:///captured-label.jpg" };
    const takePhoto = jest.fn().mockResolvedValue(fakePhoto);
    const tree = mount(
      <LabelCaptureScreen
        session={SESSION}
        onUploaded={jest.fn()}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={takePhoto}
        upload={jest.fn().mockResolvedValue(makeEvent())}
      />,
    );

    await act(async () => {
      press(tree, "Take photo");
    });

    // Preview controls appear; shutter disappears.
    expect(hasA11yLabel(tree, "Upload label")).toBe(true);
    expect(hasA11yLabel(tree, "Retake photo")).toBe(true);
    expect(hasA11yLabel(tree, "Save this photo")).toBe(true);
    expect(hasA11yLabel(tree, "Take photo")).toBe(false);
  });

  it("retake returns to the camera phase", async () => {
    const fakePhoto = { uri: "file:///captured-label.jpg" };
    const takePhoto = jest.fn().mockResolvedValue(fakePhoto);
    const tree = mount(
      <LabelCaptureScreen
        session={SESSION}
        onUploaded={jest.fn()}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={takePhoto}
        upload={jest.fn().mockResolvedValue(makeEvent())}
      />,
    );

    await act(async () => {
      press(tree, "Take photo");
    });
    press(tree, "Retake photo");

    // Back to camera: shutter visible, preview controls gone.
    expect(hasA11yLabel(tree, "Take photo")).toBe(true);
    expect(hasA11yLabel(tree, "Upload label")).toBe(false);
  });
});

// ─── Upload flow ─────────────────────────────────────────────────────────────

describe("LabelCaptureScreen – upload", () => {
  it("calls onUploaded with the created pending event on a successful upload", async () => {
    const createdEvent = makeEvent({ id: "label-server-1" });
    const upload = jest.fn().mockResolvedValue(createdEvent);
    const onUploaded = jest.fn();
    const tree = mount(
      <LabelCaptureScreen
        session={SESSION}
        onUploaded={onUploaded}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: "file:///label.jpg" })}
        upload={upload}
      />,
    );

    await act(async () => {
      press(tree, "Take photo");
    });
    await act(async () => {
      press(tree, "Upload label");
    });

    expect(onUploaded).toHaveBeenCalledTimes(1);
    expect(onUploaded).toHaveBeenCalledWith(createdEvent);
  });

  it("sends save=false by default (discard-by-default retention)", async () => {
    const upload = jest.fn().mockResolvedValue(makeEvent());
    const tree = mount(
      <LabelCaptureScreen
        session={SESSION}
        onUploaded={jest.fn()}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: "file:///label.jpg" })}
        upload={upload}
      />,
    );

    await act(async () => {
      press(tree, "Take photo");
    });
    await act(async () => {
      press(tree, "Upload label");
    });

    // The second argument to upload is savePhoto; defaults to false.
    expect(upload).toHaveBeenCalledWith("file:///label.jpg", false);
  });

  it("sends save=true when the save-photo toggle is switched on", async () => {
    const upload = jest.fn().mockResolvedValue(makeEvent());
    const tree = mount(
      <LabelCaptureScreen
        session={SESSION}
        onUploaded={jest.fn()}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: "file:///label.jpg" })}
        upload={upload}
      />,
    );

    await act(async () => {
      press(tree, "Take photo");
    });

    // Toggle save-photo on.
    const switchNode = tree.root.find(
      (n) => n.props.accessibilityLabel === "Save this photo" && typeof n.props.onValueChange === "function",
    );
    act(() => {
      switchNode.props.onValueChange(true);
    });

    await act(async () => {
      press(tree, "Upload label");
    });

    expect(upload).toHaveBeenCalledWith("file:///label.jpg", true);
  });

  it("shows an error when the upload fails and does not call onUploaded", async () => {
    const upload = jest
      .fn()
      .mockRejectedValue(new LabelUploadApiError(500, "We couldn't upload the label (status 500)."));
    const onUploaded = jest.fn();
    const tree = mount(
      <LabelCaptureScreen
        session={SESSION}
        onUploaded={onUploaded}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: "file:///label.jpg" })}
        upload={upload}
      />,
    );

    await act(async () => {
      press(tree, "Take photo");
    });
    await act(async () => {
      press(tree, "Upload label");
    });

    expect(onUploaded).not.toHaveBeenCalled();
    // Error is shown; the message must not contain image bytes or sensitive content.
    const content = textContent(tree);
    expect(content).toContain("couldn't upload");
    expect(content).not.toMatch(/file:|data:|base64/);
  });

  it("upload failure error does not echo image URI or bytes", async () => {
    const sensitiveUri = "file:///private/user/captured-private.jpg";
    const upload = jest
      .fn()
      .mockRejectedValue(new LabelUploadApiError(500, "We couldn't upload the label (status 500)."));
    const tree = mount(
      <LabelCaptureScreen
        session={SESSION}
        onUploaded={jest.fn()}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: sensitiveUri })}
        upload={upload}
      />,
    );

    await act(async () => {
      press(tree, "Take photo");
    });
    await act(async () => {
      press(tree, "Upload label");
    });

    const content = textContent(tree);
    // Error message must not contain the image URI or any path-like content.
    expect(content).not.toContain(sensitiveUri);
    expect(content).not.toContain("private");
    expect(content).not.toContain("captured-private");
  });

  it("shows the loading indicator during upload", async () => {
    let resolveUpload!: (e: LogEventDTO) => void;
    const upload = jest.fn().mockReturnValue(
      new Promise<LogEventDTO>((resolve) => { resolveUpload = resolve; }),
    );
    const tree = mount(
      <LabelCaptureScreen
        session={SESSION}
        onUploaded={jest.fn()}
        onClose={jest.fn()}
        permissionsHook={makeGrantedHook()}
        takePhoto={jest.fn().mockResolvedValue({ uri: "file:///label.jpg" })}
        upload={upload}
      />,
    );

    await act(async () => {
      press(tree, "Take photo");
    });
    act(() => {
      press(tree, "Upload label");
    });

    // While upload is in flight, a spinner is shown.
    expect(hasA11yLabel(tree, "Uploading label")).toBe(true);
    expect(hasA11yLabel(tree, "Upload label")).toBe(false);

    await act(async () => {
      resolveUpload(makeEvent());
    });
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
