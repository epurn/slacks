/**
 * Tests for CameraCapture (FTY-195).
 *
 * Covers:
 * - The permission CTA (Allow Camera Access / Open Settings — the gate is
 *   shared) renders with the theme's amber accent fill and accentForeground
 *   label, in both light and dark, replacing the former hardcoded system-blue
 *   `#0A84FF` fill. Asserting the rendered fill equals the theme accent token
 *   in both schemes also rules out a leftover `#0A84FF` literal, since that
 *   fixed value could not match both the light and dark accent colours.
 */

import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { PermissionStatus } from "expo";
import type { PermissionResponse } from "expo";

import { CameraCapture } from "./CameraCapture";
import { ThemeProvider, lightPalette, darkPalette } from "@/theme";

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

function hookFor(
  permission: PermissionResponse,
): () => [PermissionResponse, () => Promise<PermissionResponse>, () => Promise<PermissionResponse>] {
  return () => [
    permission,
    jest.fn().mockResolvedValue(permission),
    jest.fn().mockResolvedValue(permission),
  ];
}

function mount(
  element: React.ReactElement,
  scheme: "light" | "dark" = "light",
): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(<ThemeProvider override={scheme}>{element}</ThemeProvider>);
  });
  return tree;
}

function findButton(tree: ReactTestRenderer, label: string) {
  return tree.root.find(
    (n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function",
  );
}

function findLabel(tree: ReactTestRenderer, text: string) {
  return tree.root.find((n) => n.props.children === text);
}

function flatten(style: unknown): Record<string, unknown> {
  return Array.isArray(style) ? Object.assign({}, ...style) : (style as Record<string, unknown>);
}

// ─── Accent ──────────────────────────────────────────────────────────────────

describe("CameraCapture – permission CTA accent", () => {
  it("renders 'Allow Camera Access' with the theme accent fill and foreground label in light mode", () => {
    const undetermined = makePermission({ status: PermissionStatus.UNDETERMINED });
    const tree = mount(
      <CameraCapture onClose={jest.fn()} rationale="Test rationale" permissionsHook={hookFor(undetermined)}>
        {() => null}
      </CameraCapture>,
      "light",
    );

    const button = flatten(findButton(tree, "Allow camera access").props.style);
    expect(button.backgroundColor).toBe(lightPalette.accent);
    expect(button.backgroundColor).not.toBe("#0A84FF");

    const label = flatten(findLabel(tree, "Allow Camera Access").props.style);
    expect(label.color).toBe(lightPalette.accentForeground);
  });

  it("renders 'Allow Camera Access' with the theme accent fill and foreground label in dark mode", () => {
    const undetermined = makePermission({ status: PermissionStatus.UNDETERMINED });
    const tree = mount(
      <CameraCapture onClose={jest.fn()} rationale="Test rationale" permissionsHook={hookFor(undetermined)}>
        {() => null}
      </CameraCapture>,
      "dark",
    );

    const button = flatten(findButton(tree, "Allow camera access").props.style);
    expect(button.backgroundColor).toBe(darkPalette.accent);
    expect(button.backgroundColor).not.toBe("#0A84FF");

    const label = flatten(findLabel(tree, "Allow Camera Access").props.style);
    expect(label.color).toBe(darkPalette.accentForeground);
  });

  it("renders the blocked-state 'Open Settings' CTA with the same accent fill (shared gate)", () => {
    const blocked = makePermission({ status: PermissionStatus.DENIED, canAskAgain: false });
    const tree = mount(
      <CameraCapture onClose={jest.fn()} rationale="Test rationale" permissionsHook={hookFor(blocked)}>
        {() => null}
      </CameraCapture>,
      "light",
    );

    const button = flatten(findButton(tree, "Open Settings").props.style);
    expect(button.backgroundColor).toBe(lightPalette.accent);

    const label = flatten(findLabel(tree, "Open Settings").props.style);
    expect(label.color).toBe(lightPalette.accentForeground);
  });
});
