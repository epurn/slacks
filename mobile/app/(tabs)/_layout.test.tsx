import { act, create } from "react-test-renderer";

import TabLayout from "./_layout";
import { ThemeProvider } from "@/theme";

// Capture the `screenOptions` the layout hands to expo-router's `Tabs` so the
// tab-bar background material can be asserted without a live navigation tree.
let capturedScreenOptions: Record<string, unknown> | undefined;

jest.mock("expo-router", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  const Tabs = ({
    screenOptions,
    children,
  }: {
    screenOptions: Record<string, unknown>;
    children: React.ReactNode;
  }) => {
    capturedScreenOptions = screenOptions;
    return ReactLib.createElement(ReactLib.Fragment, null, children);
  };
  Tabs.Screen = jest.fn(() => null);
  return { Tabs };
});

jest.mock("expo-blur", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactNative = require("react-native");
  return {
    BlurView: (props: Record<string, unknown>) =>
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      require("react").createElement(ReactNative.View, {
        testID: "tab-bar-blur",
        ...props,
      }),
  };
});

jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactNative = require("react-native");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  return {
    SymbolView: ({ name }: { name: string }) =>
      ReactLib.createElement(ReactNative.View, { testID: `sf-symbol-${name}` }),
  };
});

function renderLayout(override: "light" | "dark") {
  capturedScreenOptions = undefined;
  act(() => {
    create(
      <ThemeProvider override={override}>
        <TabLayout />
      </ThemeProvider>,
    );
  });
  return capturedScreenOptions!;
}

describe("TabLayout tab-bar material (FTY-185)", () => {
  it("backs the tab bar with a real expo-blur .ultraThin BlurView (light)", () => {
    const options = renderLayout("light");

    // The bar floats over content and lets the blur show through.
    expect((options.tabBarStyle as Record<string, unknown>).position).toBe(
      "absolute",
    );
    expect(
      (options.tabBarStyle as Record<string, unknown>).backgroundColor,
    ).toBe("transparent");

    const bg = (
      options.tabBarBackground as () => React.ReactElement<{
        tint: string;
        intensity: number;
      }>
    )();
    expect(bg.props.tint).toBe("systemUltraThinMaterialLight");
    expect(bg.props.intensity).toBe(100);
  });

  it("uses the dark .ultraThin material in dark mode", () => {
    const options = renderLayout("dark");
    const bg = (
      options.tabBarBackground as () => React.ReactElement<{ tint: string }>
    )();
    expect(bg.props.tint).toBe("systemUltraThinMaterialDark");
  });
});
