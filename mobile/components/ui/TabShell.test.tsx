import React from 'react';
import { act, create } from 'react-test-renderer';
import { useColorScheme } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { ThemeProvider } from '@/theme';
import TabLayout from '@/app/(tabs)/_layout';

// ---------------------------------------------------------------------------
// Mock expo-symbols — replace SymbolView with a View stub that exposes the
// SF Symbol name via testID so tests can assert which glyph was requested
// without requiring the native module.
// ---------------------------------------------------------------------------

jest.mock('expo-symbols', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require('react');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require('react-native');
  return {
    SymbolView: ({
      name,
      accessibilityLabel,
    }: {
      name: string;
      tintColor?: string;
      size?: number;
      accessibilityLabel?: string;
    }) =>
      React.createElement(View, {
        testID: `sf-symbol-${String(name)}`,
        accessibilityLabel,
      }),
  };
});

// ---------------------------------------------------------------------------
// Mock expo-router — replace Tabs with simple View-based stubs so the layout
// can be rendered without the full navigation runtime.
// ---------------------------------------------------------------------------

jest.mock('expo-router', () => {
  // require() inside factory — jest.mock() factories run before module-scope
  // imports and cannot close over them.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require('react');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View, Text } = require('react-native');

  const MockTabsScreen = ({
    name,
    options,
  }: {
    name: string;
    options?: {
      title?: string;
      tabBarAccessibilityLabel?: string;
      tabBarIcon?: (opts: { color: string; focused: boolean; size: number }) => React.ReactNode;
    };
  }) => {
    // Invoke tabBarIcon so the icon is included in the rendered tree.
    const icon = options?.tabBarIcon?.({ color: '#000000', focused: true, size: 22 });
    return React.createElement(
      View,
      { testID: `tab-screen-${name}` },
      React.createElement(Text, {}, options?.title ?? name),
      icon
        ? React.createElement(View, { testID: `tab-icon-${name}` }, icon)
        : null,
    );
  };

  const MockTabs = ({
    children,
    screenOptions,
  }: {
    children: React.ReactNode;
    screenOptions?: {
      headerShown?: boolean;
      headerRight?: () => React.ReactNode;
      [key: string]: unknown;
    };
  }) => {
    // Render a marker node so tests can assert headerShown: false is set globally.
    const headerHiddenMarker =
      screenOptions?.headerShown === false
        ? React.createElement(View, { testID: 'tabs-native-header-hidden' })
        : null;
    // Invoke headerRight if present (should be absent after FTY-151).
    const headerRight = screenOptions?.headerRight ? screenOptions.headerRight() : null;
    return React.createElement(
      View,
      { testID: 'tabs-container' },
      headerHiddenMarker,
      headerRight,
      children,
    );
  };

  MockTabs.Screen = MockTabsScreen;

  return {
    Tabs: MockTabs,
    useRouter: jest.fn(() => ({ push: jest.fn() })),
    useLocalSearchParams: jest.fn(() => ({})),
  };
});

// jest-expo's preset already mocks useColorScheme as a jest.fn() returning 'light'.
const mockUseColorScheme = useColorScheme as jest.MockedFunction<typeof useColorScheme>;

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

function mount() {
  let tree: ReturnType<typeof create> | null = null;
  act(() => {
    tree = create(
      React.createElement(
        SafeAreaProvider,
        {
          initialMetrics: {
            frame: { x: 0, y: 0, width: 390, height: 844 },
            insets: { top: 47, left: 0, right: 0, bottom: 34 },
          },
        },
        React.createElement(
          ThemeProvider,
          { override: 'light' },
          React.createElement(TabLayout),
        ),
      ),
    );
  });
  return tree!;
}

// ---------------------------------------------------------------------------
// TabLayout tests
// ---------------------------------------------------------------------------

describe('TabLayout', () => {
  beforeEach(() => {
    mockUseColorScheme.mockReturnValue('light');
  });

  it('renders a tab-screen for "index" with title "Today"', () => {
    const tree = mount();
    const node = tree.root.find((n) => n.props.testID === 'tab-screen-index');
    expect(node).toBeTruthy();
    const textNode = node.find(
      (n) => (n.type as unknown as string) === 'Text' && n.props.children === 'Today',
    );
    expect(textNode).toBeTruthy();
  });

  it('renders a tab-screen for "trends" with title "Trends"', () => {
    const tree = mount();
    const node = tree.root.find((n) => n.props.testID === 'tab-screen-trends');
    expect(node).toBeTruthy();
    const textNode = node.find(
      (n) => (n.type as unknown as string) === 'Text' && n.props.children === 'Trends',
    );
    expect(textNode).toBeTruthy();
  });

  it('does not render a tab-screen for any unexpected name', () => {
    const tree = mount();
    const knownScreens = ['index', 'trends'];
    const unexpectedScreens = tree.root.findAll(
      (n) =>
        typeof n.props.testID === 'string' &&
        n.props.testID.startsWith('tab-screen-') &&
        !knownScreens.some((name) => n.props.testID === `tab-screen-${name}`),
    );
    expect(unexpectedScreens).toHaveLength(0);
  });

  it('sets headerShown: false globally so the native header is suppressed on every tab', () => {
    // The mock renders a marker node when screenOptions.headerShown === false.
    const tree = mount();
    const marker = tree.root.find(
      (n) => n.props.testID === 'tabs-native-header-hidden',
    );
    expect(marker).toBeTruthy();
  });

  it('does not render a global headerRight gear (gear lives in per-screen ScreenHeader after FTY-151)', () => {
    const tree = mount();
    // No element with "Open profile" label should exist in the tab shell —
    // the gear is now owned by each screen's ScreenHeader, not the layout.
    const gearButtons = tree.root.findAll(
      (n) => n.props.accessibilityLabel === 'Open profile',
    );
    expect(gearButtons).toHaveLength(0);
  });

  // -------------------------------------------------------------------------
  // SF Symbol icon assertions (FTY-145) — emoji replaced with AppIcon
  // -------------------------------------------------------------------------

  it('Today tab icon renders SF Symbol "sun.max" (not an emoji Text)', () => {
    const tree = mount();
    const iconContainer = tree.root.find((n) => n.props.testID === 'tab-icon-index');
    const symbol = iconContainer.find((n) => n.props.testID === 'sf-symbol-sun.max');
    expect(symbol).toBeTruthy();
  });

  it('Trends tab icon renders SF Symbol "chart.line.uptrend.xyaxis" (not an emoji Text)', () => {
    const tree = mount();
    const iconContainer = tree.root.find((n) => n.props.testID === 'tab-icon-trends');
    const symbol = iconContainer.find(
      (n) => n.props.testID === 'sf-symbol-chart.line.uptrend.xyaxis',
    );
    expect(symbol).toBeTruthy();
  });

  it('contains no emoji codepoints as chrome glyphs in any tab icon', () => {
    const tree = mount();
    // Emoji range guard: collect every Text node in the rendered tree and
    // assert its content is free of common emoji codepoints that were
    // previously used as tab/header chrome.
    const emojiPattern = /[\u{1F300}-\u{1FFFF}]|\u{2699}|\u{2600}|＋/u;
    const textNodes = tree.root.findAll(
      (n) => (n.type as unknown as string) === 'Text' && typeof n.props.children === 'string',
    );
    for (const node of textNodes) {
      expect(node.props.children as string).not.toMatch(emojiPattern);
    }
  });
});
