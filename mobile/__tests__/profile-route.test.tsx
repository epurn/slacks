/**
 * Route tests for the Profile / Settings native header (FTY-182, FTY-305).
 *
 * The /profile route configures the native stack header: a large-title bar with a
 * Done action that dismisses back to where the gear was opened. SettingsScreen's
 * behaviour (editing, target-reveal, cadence, sign-out) is covered by
 * SettingsScreen.test.tsx and stubbed here so this test isolates the header wiring.
 *
 * FTY-305: Done is handed through `unstable_headerRightItems` (a custom item) rather
 * than the classic `headerRight` element, so it can carry `hidesSharedBackground`.
 * On iOS 26 the navigation bar draws a shared "glass" capsule behind a bar-button
 * item — the white rectangle the dogfooding pass flagged — and the classic
 * `headerRight` element has no way to opt out. These tests lock the item shape,
 * the hidden shared background, and the element's inert/stable props; the actual
 * iOS-26 native flash can only be proven by the running-app evidence in the PR.
 *
 * This lives under mobile/__tests__/ rather than beside the route in app/: everything
 * under app/ is an expo-router route (a recursive require.context), so a `*.test.tsx`
 * there gets bundled as a route and its top-level `jest.fn()` crashes the E2E
 * dev-client build. The reachable Profile user flow is proven end-to-end by the
 * .maestro/profile.yaml flow; this file keeps the isolated header-options coverage.
 */

import React from "react";
import { StyleSheet } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { ThemeProvider } from "@/theme";
import { lightPalette, darkPalette } from "@/theme/colors";
import ProfileRoute from "@/app/profile";

// ─────────────────────────────────────────────────────────────────────────────
// Capture the options handed to the native <Stack.Screen>, and the router.
// ─────────────────────────────────────────────────────────────────────────────
const mockBack = jest.fn();
let mockCapturedOptions: any = null;

jest.mock("expo-router", () => ({
  useRouter: () => ({ back: mockBack, push: jest.fn(), replace: jest.fn() }),
  Stack: {
    Screen: (props: { options: any }) => {
      mockCapturedOptions = props.options;
      return null;
    },
  },
}));

// The route only wires header chrome; SettingsScreen internals are tested elsewhere.
jest.mock("@/components/SettingsScreen", () => ({
  SettingsScreen: () => null,
}));

function renderRoute(colorScheme: "light" | "dark" = "light"): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <ThemeProvider override={colorScheme}>
        <ProfileRoute />
      </ThemeProvider>,
    );
  });
  return tree;
}

// The single custom right-header item that carries Done. `renderRoute()` must run
// first so `mockCapturedOptions` is populated.
function doneItem(): {
  type: string;
  hidesSharedBackground?: boolean;
  element: React.ReactElement;
} {
  const items = mockCapturedOptions.unstable_headerRightItems();
  expect(Array.isArray(items)).toBe(true);
  expect(items).toHaveLength(1);
  return items[0];
}

// Render just the Done element (the custom item's `element`) for prop inspection.
function renderDone(): ReactTestRenderer {
  let headerTree!: ReactTestRenderer;
  act(() => {
    headerTree = create(<>{doneItem().element}</>);
  });
  return headerTree;
}

describe("Profile native header", () => {
  beforeEach(() => {
    mockCapturedOptions = null;
    mockBack.mockClear();
  });

  it("configures a native large-title header titled Profile", () => {
    renderRoute();
    expect(mockCapturedOptions).toBeTruthy();
    expect(mockCapturedOptions.headerShown).toBe(true);
    expect(mockCapturedOptions.title).toBe("Profile");
    expect(mockCapturedOptions.headerLargeTitle).toBe(true);
  });

  it("hides the back chevron so Done is the sole dismissal", () => {
    renderRoute();
    expect(mockCapturedOptions.headerBackVisible).toBe(false);
  });

  it("renders a Done action that dismisses the screen", () => {
    renderRoute();
    expect(typeof mockCapturedOptions.unstable_headerRightItems).toBe(
      "function",
    );
    // Done keeps the classic `headerRight` element out of the tree entirely — it
    // moved to `unstable_headerRightItems` so it can hide the shared background.
    expect(mockCapturedOptions.headerRight).toBeUndefined();

    const headerTree = renderDone();
    const done = headerTree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Done" &&
        typeof n.props.onPress === "function",
    );
    expect(done).toBeTruthy();

    act(() => {
      done.props.onPress();
    });
    expect(mockBack).toHaveBeenCalledTimes(1);
  });

  it("hands Done through a custom right item that hides the iOS 26 shared background", () => {
    // The white rectangle FTY-305 removes is iOS 26's shared bar-button "glass"
    // capsule. The classic `headerRight` element cannot opt out, so Done is a
    // custom `unstable_headerRightItems` entry with `hidesSharedBackground: true`
    // (maps to UIBarButtonItem.hidesSharedBackground) — only the label draws.
    renderRoute();
    const item = doneItem();
    expect(item.type).toBe("custom");
    expect(item.hidesSharedBackground).toBe(true);
  });

  it("renders the Done label with the AA-safe accent text token, not raw accent", () => {
    // The visible Done text is normal-size, so it must meet the WCAG AA contrast bar
    // on the light surface. The decorative `accent` token fails there (~2.14:1); the
    // AA-safe `accentText` is required for both light and dark surfaces.
    for (const scheme of ["light", "dark"] as const) {
      mockCapturedOptions = null;
      renderRoute(scheme);
      const palette = scheme === "light" ? lightPalette : darkPalette;

      const headerTree = renderDone();
      const label = headerTree.root.find(
        (n) =>
          (n.type as unknown as string) === "Text" &&
          n.props.children === "Done",
      );
      const { color } = StyleSheet.flatten(label.props.style);
      expect(color).toBe(palette.accentText);
    }
    // On the light surface the decorative accent fails AA (~2.14:1); accentText does not.
    expect(lightPalette.accentText).not.toBe(lightPalette.accent);
  });

  it("keeps the Done press visually inert and layout-stable (FTY-305)", () => {
    // The pressed visual state must not draw a white flash or shift the header:
    // no pressed-dependent background/fill, opacity, transform/scale, padding,
    // margin, border, or size, and no Android ripple. The bounds are identical
    // whether or not the button is pressed, and the 44pt target is stable.
    renderRoute();
    const headerTree = renderDone();
    const done = headerTree.root.find(
      (n) => n.props.testID === "profile-done",
    );

    // Ripple never applies (guards Android from a flashing feedback rectangle).
    expect(done.props.android_ripple).toBeNull();

    // The style resolves identically for the unpressed and pressed states — so no
    // press-only paint can appear. Support both a static style and a
    // `({ pressed }) => …` function form.
    const resolveStyle = (pressed: boolean) => {
      const s = done.props.style;
      return StyleSheet.flatten(typeof s === "function" ? s({ pressed }) : s);
    };
    const rest = resolveStyle(false);
    const pressed = resolveStyle(true);
    expect(pressed).toEqual(rest);

    // None of the pressed-flash-capable properties are set in either state.
    for (const style of [rest, pressed]) {
      expect(style.backgroundColor).toBeUndefined();
      expect(style.opacity).toBeUndefined();
      expect(style.transform).toBeUndefined();
      expect(style.borderWidth).toBeUndefined();
      expect(style.padding).toBeUndefined();
      expect(style.paddingHorizontal).toBeUndefined();
      expect(style.paddingVertical).toBeUndefined();
      expect(style.margin).toBeUndefined();
    }

    // The touch target stays at least 44pt via stable bounds (not a pressed
    // expansion), and hitSlop keeps the effective target comfortable.
    expect(rest.minHeight).toBeGreaterThanOrEqual(44);
    expect(rest.minWidth).toBeGreaterThanOrEqual(44);
    expect(done.props.hitSlop).toEqual({
      top: 12,
      bottom: 12,
      left: 12,
      right: 12,
    });
  });

  it("keeps the header opaque so content is inset, not floated under it", () => {
    renderRoute();
    // A transparent header would float over content and need a manual offset; the
    // route keeps it opaque so the native stack lays content below the bar.
    expect(mockCapturedOptions.headerTransparent).toBeUndefined();
    expect(mockCapturedOptions.headerBlurEffect).toBeUndefined();
  });

  it("matches the header background to the resolved appearance surface", () => {
    renderRoute("light");
    const lightBg = mockCapturedOptions.headerStyle.backgroundColor;
    expect(lightBg).toBeTruthy();

    mockCapturedOptions = null;
    renderRoute("dark");
    const darkBg = mockCapturedOptions.headerStyle.backgroundColor;
    expect(darkBg).toBeTruthy();
    // A Light/Dark override must change the header surface, not the raw system scheme.
    expect(darkBg).not.toBe(lightBg);
  });
});
