/**
 * Tests for the barcode scanner screen and camera permission flows (FTY-063).
 *
 * Covers:
 * - Permission state machine: undetermined → request, granted → camera,
 *   blocked → settings path.
 * - onBarcodeScanned is called with the raw barcode string on a successful scan.
 * - Only the barcode string is passed through; no frame, image, or URI is
 *   included (the ephemeral-frame contract).
 * - Accessible labels on camera controls, permission rationale, and close.
 * - onClose is called when the close button is pressed.
 */

import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";
import { PermissionStatus } from "expo";

import { BarcodeScannerScreen } from "./BarcodeScannerScreen";
import type { PermissionResponse } from "expo";

// ─── Mocks ───────────────────────────────────────────────────────────────────

// triggerScan is set by the MockCameraView to let tests fire a simulated scan.
// It is prefixed "mock" so jest.mock() factories can reference it.
let mockTriggerScan: ((data: string) => void) | undefined;

jest.mock("expo-camera", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require("react-native");
  const MockCameraView = jest.fn().mockImplementation(
    ({ onBarcodeScanned }: { onBarcodeScanned?: (r: { data: string; type: string; cornerPoints: unknown[]; bounds: unknown }) => void }) => {
      // Expose a simplified trigger; the mock wraps the required BarcodeScanningResult fields.
      mockTriggerScan = onBarcodeScanned
        ? (data: string) =>
            onBarcodeScanned({
              data,
              type: "ean13",
              cornerPoints: [],
              bounds: { origin: { x: 0, y: 0 }, size: { width: 0, height: 0 } },
            })
        : undefined;
      return ReactLib.createElement(View, {
        testID: "camera-view",
        accessibilityLabel: "Camera viewfinder",
      });
    },
  );
  return { CameraView: MockCameraView };
});

jest.mock("expo-linking", () => ({
  openSettings: jest.fn().mockResolvedValue(undefined),
}));

// ─── Helpers ─────────────────────────────────────────────────────────────────

function makePermission(overrides: Partial<PermissionResponse>): PermissionResponse {
  return {
    status: PermissionStatus.UNDETERMINED,
    granted: false,
    canAskAgain: true,
    expires: "never",
    ...overrides,
  };
}

function makePermissionsHook(
  permission: PermissionResponse | null,
  requestFn = jest.fn().mockResolvedValue(undefined),
): () => [PermissionResponse | null, () => Promise<PermissionResponse>, () => Promise<PermissionResponse>] {
  return () => [
    permission,
    requestFn,
    jest.fn().mockResolvedValue(permission ?? makePermission({})),
  ];
}

const SAFE_AREA_METRICS = {
  frame: { x: 0, y: 0, width: 390, height: 844 },
  insets: { top: 47, left: 0, right: 0, bottom: 34 },
};

function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
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
  return (
    tree.root.findAll((n) => n.props.accessibilityLabel === label).length > 0
  );
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

// ─── Permission state machine ─────────────────────────────────────────────────

describe("BarcodeScannerScreen – permission flows", () => {
  it("shows the rationale and a request button when permission is undetermined", () => {
    const permission = makePermission({
      status: PermissionStatus.UNDETERMINED,
      granted: false,
    });
    const tree = mount(
      <BarcodeScannerScreen
        onBarcodeScanned={jest.fn()}
        onClose={jest.fn()}
        permissionsHook={makePermissionsHook(permission)}
      />,
    );
    const content = textContent(tree);
    expect(content).toContain("camera");
    expect(hasA11yLabel(tree, "Allow camera access")).toBe(true);
  });

  it("calls requestPermission when the request button is pressed", async () => {
    const requestPermission = jest
      .fn()
      .mockResolvedValue(
        makePermission({ status: PermissionStatus.GRANTED, granted: true }),
      );
    const permission = makePermission({
      status: PermissionStatus.UNDETERMINED,
      granted: false,
    });
    const tree = mount(
      <BarcodeScannerScreen
        onBarcodeScanned={jest.fn()}
        onClose={jest.fn()}
        permissionsHook={makePermissionsHook(permission, requestPermission)}
      />,
    );

    await act(async () => {
      press(tree, "Allow camera access");
    });

    expect(requestPermission).toHaveBeenCalledTimes(1);
  });

  it("shows the camera view when permission is granted", () => {
    const permission = makePermission({
      status: PermissionStatus.GRANTED,
      granted: true,
    });
    const tree = mount(
      <BarcodeScannerScreen
        onBarcodeScanned={jest.fn()}
        onClose={jest.fn()}
        permissionsHook={makePermissionsHook(permission)}
      />,
    );
    expect(hasA11yLabel(tree, "Camera viewfinder")).toBe(true);
  });

  it("shows Open Settings when camera is permanently blocked (denied, canAskAgain=false)", () => {
    const permission = makePermission({
      status: PermissionStatus.DENIED,
      granted: false,
      canAskAgain: false,
    });
    const tree = mount(
      <BarcodeScannerScreen
        onBarcodeScanned={jest.fn()}
        onClose={jest.fn()}
        permissionsHook={makePermissionsHook(permission)}
      />,
    );
    expect(hasA11yLabel(tree, "Open Settings")).toBe(true);
    // No "Allow camera access" button when permanently blocked.
    expect(hasA11yLabel(tree, "Allow camera access")).toBe(false);
  });
});

// ─── Barcode scan callback ────────────────────────────────────────────────────

describe("BarcodeScannerScreen – scan callback", () => {
  beforeEach(() => {
    mockTriggerScan = undefined;
  });

  it("calls onBarcodeScanned with the raw barcode string on a successful scan", () => {
    const onBarcodeScanned = jest.fn();
    const permission = makePermission({
      status: PermissionStatus.GRANTED,
      granted: true,
    });
    mount(
      <BarcodeScannerScreen
        onBarcodeScanned={onBarcodeScanned}
        onClose={jest.fn()}
        permissionsHook={makePermissionsHook(permission)}
      />,
    );

    act(() => {
      mockTriggerScan?.("5901234123457");
    });

    expect(onBarcodeScanned).toHaveBeenCalledTimes(1);
    expect(onBarcodeScanned).toHaveBeenCalledWith("5901234123457");
  });

  it("only passes the barcode string — no image, frame, URI, or blob", () => {
    const onBarcodeScanned = jest.fn();
    const permission = makePermission({
      status: PermissionStatus.GRANTED,
      granted: true,
    });
    mount(
      <BarcodeScannerScreen
        onBarcodeScanned={onBarcodeScanned}
        onClose={jest.fn()}
        permissionsHook={makePermissionsHook(permission)}
      />,
    );

    act(() => {
      mockTriggerScan?.("5901234123457");
    });

    // The callback receives exactly one string argument — no second argument,
    // no object with image data, no URI.
    const [arg] = onBarcodeScanned.mock.calls[0] as [string];
    expect(typeof arg).toBe("string");
    expect(onBarcodeScanned.mock.calls[0]).toHaveLength(1);
    expect(arg).not.toMatch(/^(file|content|data):/);
  });

  it("does not call onBarcodeScanned twice for a rapid double-scan", () => {
    const onBarcodeScanned = jest.fn();
    const permission = makePermission({
      status: PermissionStatus.GRANTED,
      granted: true,
    });
    mount(
      <BarcodeScannerScreen
        onBarcodeScanned={onBarcodeScanned}
        onClose={jest.fn()}
        permissionsHook={makePermissionsHook(permission)}
      />,
    );

    act(() => {
      mockTriggerScan?.("5901234123457");
      mockTriggerScan?.("5901234123457");
    });

    expect(onBarcodeScanned).toHaveBeenCalledTimes(1);
  });
});

// ─── Close / cancel ───────────────────────────────────────────────────────────

describe("BarcodeScannerScreen – close", () => {
  it("calls onClose when the close button is pressed (permission undetermined)", () => {
    const onClose = jest.fn();
    const permission = makePermission({
      status: PermissionStatus.UNDETERMINED,
      granted: false,
    });
    const tree = mount(
      <BarcodeScannerScreen
        onBarcodeScanned={jest.fn()}
        onClose={onClose}
        permissionsHook={makePermissionsHook(permission)}
      />,
    );
    press(tree, "Close scanner");
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("calls onClose when the close button is pressed (camera active)", () => {
    const onClose = jest.fn();
    const permission = makePermission({
      status: PermissionStatus.GRANTED,
      granted: true,
    });
    const tree = mount(
      <BarcodeScannerScreen
        onBarcodeScanned={jest.fn()}
        onClose={onClose}
        permissionsHook={makePermissionsHook(permission)}
      />,
    );
    press(tree, "Close scanner");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

// ─── Accessibility ────────────────────────────────────────────────────────────

describe("BarcodeScannerScreen – accessibility", () => {
  it("permission rationale has an accessible text label", () => {
    const permission = makePermission({
      status: PermissionStatus.UNDETERMINED,
      granted: false,
    });
    const tree = mount(
      <BarcodeScannerScreen
        onBarcodeScanned={jest.fn()}
        onClose={jest.fn()}
        permissionsHook={makePermissionsHook(permission)}
      />,
    );
    // The rationale node carries accessibilityRole="text" and accessible text.
    const rationaleNodes = tree.root.findAll(
      (n) => n.props.accessibilityRole === "text",
    );
    expect(rationaleNodes.length).toBeGreaterThan(0);
  });

  it("close button is accessible in all permission states", () => {
    const states: (PermissionResponse | null)[] = [
      null,
      makePermission({ status: PermissionStatus.UNDETERMINED, granted: false }),
      makePermission({ status: PermissionStatus.GRANTED, granted: true }),
      makePermission({
        status: PermissionStatus.DENIED,
        granted: false,
        canAskAgain: false,
      }),
    ];
    for (const perm of states) {
      const tree = mount(
        <BarcodeScannerScreen
          onBarcodeScanned={jest.fn()}
          onClose={jest.fn()}
          permissionsHook={makePermissionsHook(perm)}
        />,
      );
      expect(hasA11yLabel(tree, "Close scanner")).toBe(true);
    }
  });

  it("camera viewfinder has an accessible label when camera is active", () => {
    const permission = makePermission({
      status: PermissionStatus.GRANTED,
      granted: true,
    });
    const tree = mount(
      <BarcodeScannerScreen
        onBarcodeScanned={jest.fn()}
        onClose={jest.fn()}
        permissionsHook={makePermissionsHook(permission)}
      />,
    );
    expect(hasA11yLabel(tree, "Camera viewfinder")).toBe(true);
  });
});
