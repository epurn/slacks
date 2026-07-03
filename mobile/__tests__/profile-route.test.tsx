/**
 * Route tests for the Profile / Settings native header (FTY-182).
 *
 * The /profile route configures the native stack header: a large-title bar with a
 * Done action that dismisses back to where the gear was opened. SettingsScreen's
 * behaviour (editing, target-reveal, cadence, sign-out) is covered by
 * SettingsScreen.test.tsx and stubbed here so this test isolates the header wiring.
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
    const HeaderRight = mockCapturedOptions.headerRight;
    expect(typeof HeaderRight).toBe("function");

    let headerTree!: ReactTestRenderer;
    act(() => {
      headerTree = create(<>{HeaderRight()}</>);
    });
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

  it("renders the Done label with the AA-safe accent text token, not raw accent", () => {
    // The visible Done text is normal-size, so it must meet the WCAG AA contrast bar
    // on the light surface. The decorative `accent` token fails there (~2.14:1); the
    // AA-safe `accentText` is required for both light and dark surfaces.
    for (const scheme of ["light", "dark"] as const) {
      mockCapturedOptions = null;
      renderRoute(scheme);
      const palette = scheme === "light" ? lightPalette : darkPalette;

      let headerTree!: ReactTestRenderer;
      act(() => {
        headerTree = create(<>{mockCapturedOptions.headerRight()}</>);
      });
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
