import React from "react";
import { Pressable, Text, View } from "react-native";
import { act, create } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { DISPLAY_FONT_FAMILY, ThemeProvider, displayTracking, typeScale } from "@/theme";
import { ScreenHeader } from "./ScreenHeader";

// Stub expo-symbols so tests run without native modules.
jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require("react");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require("react-native");
  return {
    SymbolView: ({ name, accessibilityLabel }: { name: string; accessibilityLabel?: string }) =>
      React.createElement(View, { testID: `sf-symbol-${String(name)}`, accessibilityLabel }),
  };
});

const METRICS = {
  frame: { x: 0, y: 0, width: 390, height: 844 },
  insets: { top: 47, left: 0, right: 0, bottom: 34 },
};

function mount(element: React.ReactElement, scheme: "light" | "dark" = "light") {
  let tree: ReturnType<typeof create> | null = null;
  act(() => {
    tree = create(
      React.createElement(
        SafeAreaProvider,
        { initialMetrics: METRICS },
        React.createElement(ThemeProvider, { override: scheme }, element),
      ),
    );
  });
  return tree!;
}

describe("ScreenHeader", () => {
  it("renders the title with accessibilityRole='header'", () => {
    const tree = mount(<ScreenHeader title="Today" />);
    const header = tree.root.find(
      (n) => n.props.accessibilityRole === "header",
    );
    expect(header).toBeTruthy();
    expect(header.props.children).toBe("Today");
  });

  it("renders the title at largeTitle font size (34)", () => {
    const tree = mount(<ScreenHeader title="Trends" />);
    const header = tree.root.find(
      (n) =>
        (n.type as unknown as string) === "Text" &&
        n.props.accessibilityRole === "header",
    );
    expect(header.props.style).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ fontSize: 34 }),
      ]),
    );
  });

  it("routes the title through DisplayText (display face + tracking at typeScale.largeTitle)", () => {
    const tree = mount(<ScreenHeader title="Today" />);
    const header = tree.root.find(
      (n) =>
        (n.type as unknown as string) === "Text" &&
        n.props.accessibilityRole === "header",
    );
    const flattened = (header.props.style as Record<string, unknown>[]).reduce(
      (acc, s) => (s && typeof s === "object" ? { ...acc, ...s } : acc),
      {} as Record<string, unknown>,
    );
    expect(flattened.fontFamily).toBe(DISPLAY_FONT_FAMILY);
    expect(flattened.letterSpacing).toBe(displayTracking);
    expect(flattened.fontSize).toBe(typeScale.largeTitle);
    expect(flattened.fontWeight).toBe("700");
  });

  it("renders provided right-actions", () => {
    const onPress = jest.fn();
    const tree = mount(
      <ScreenHeader
        title="Today"
        actions={
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Open profile"
            onPress={onPress}
          >
            <Text>gear</Text>
          </Pressable>
        }
      />,
    );
    const gearBtn = tree.root.find(
      (n) => n.props.accessibilityLabel === "Open profile",
    );
    expect(gearBtn).toBeTruthy();
  });

  it("applies the safe-area top inset (paddingTop = insets.top + spacing.sm = 47 + 8 = 55)", () => {
    const tree = mount(<ScreenHeader title="Trends" />);
    // The outermost View of ScreenHeader carries the dynamic paddingTop.
    const container = tree.root.find(
      (n) =>
        Array.isArray(n.props.style) &&
        n.props.style.some(
          (s: Record<string, unknown>) =>
            s && typeof s === "object" && s.paddingTop === 55,
        ),
    );
    expect(container).toBeTruthy();
  });

  it("does not impose its own horizontal padding (inherits it from the host content so the title aligns with the body)", () => {
    const tree = mount(<ScreenHeader title="Trends" />);
    const container = tree.root.find(
      (n) =>
        Array.isArray(n.props.style) &&
        n.props.style.some(
          (s: Record<string, unknown>) =>
            s && typeof s === "object" && s.paddingTop === 55,
        ),
    );
    const flattened = (container.props.style as Record<string, unknown>[]).reduce(
      (acc, s) => (s && typeof s === "object" ? { ...acc, ...s } : acc),
      {} as Record<string, unknown>,
    );
    expect(flattened.paddingHorizontal).toBeUndefined();
    expect(flattened.paddingLeft).toBeUndefined();
    expect(flattened.paddingRight).toBeUndefined();
  });

  it("renders correctly in dark mode", () => {
    const tree = mount(<ScreenHeader title="Today" />, "dark");
    const header = tree.root.find(
      (n) => n.props.accessibilityRole === "header",
    );
    expect(header).toBeTruthy();
  });

  it("renders no actions slot when actions prop is omitted", () => {
    const tree = mount(<ScreenHeader title="Today" />);
    // No button should be present.
    const buttons = tree.root.findAll(
      (n) => n.props.accessibilityRole === "button",
    );
    expect(buttons).toHaveLength(0);
  });

  // ── Gear action (moved from TabShell — gear now lives in per-screen ScreenHeader) ──

  it("renders a gear SF Symbol when a gear action is provided", () => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { AppIcon } = require("./AppIcon") as { AppIcon: React.ComponentType<{ name: string; size?: number; color?: string }> };
    const tree = mount(
      <ScreenHeader
        title="Today"
        actions={
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Open profile"
            accessibilityHint="Opens profile and settings"
            style={{ minWidth: 44, minHeight: 44, alignItems: "center", justifyContent: "center" }}
          >
            {React.createElement(AppIcon, { name: "gear", size: 22 })}
          </Pressable>
        }
      />,
    );
    const gearBtn = tree.root.find(
      (n) => n.props.accessibilityLabel === "Open profile",
    );
    expect(gearBtn).toBeTruthy();
    const symbol = gearBtn.find((n) => n.props.testID === "sf-symbol-gear");
    expect(symbol).toBeTruthy();
  });

  it("gear action has at least 44pt tap target", () => {
    const tree = mount(
      <ScreenHeader
        title="Trends"
        actions={
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Open profile"
            style={{ minWidth: 44, minHeight: 44, alignItems: "center" as const, justifyContent: "center" as const }}
          >
            <View />
          </Pressable>
        }
      />,
    );
    const gearBtn = tree.root.find(
      (n) => n.props.accessibilityLabel === "Open profile",
    );
    const style = gearBtn.props.style as { minWidth?: number; minHeight?: number };
    expect(style.minWidth).toBeGreaterThanOrEqual(44);
    expect(style.minHeight).toBeGreaterThanOrEqual(44);
  });
});
