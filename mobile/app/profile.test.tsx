/**
 * Route tests for the Profile / Settings native header (FTY-182).
 *
 * The /profile route configures the native stack header: a large-title bar with a
 * Done action that dismisses back to where the gear was opened. SettingsScreen's
 * behaviour (editing, target-reveal, cadence, sign-out) is covered by
 * SettingsScreen.test.tsx and stubbed here so this test isolates the header wiring.
 */

import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { ThemeProvider } from "@/theme";
import ProfileRoute from "./profile";

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

  it("uses the appearance-matched frost so a Light/Dark override is honoured", () => {
    renderRoute("light");
    expect(mockCapturedOptions.headerBlurEffect).toBe("systemChromeMaterialLight");

    mockCapturedOptions = null;
    renderRoute("dark");
    expect(mockCapturedOptions.headerBlurEffect).toBe("systemChromeMaterialDark");
  });
});
