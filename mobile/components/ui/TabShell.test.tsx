import React from 'react';
import { act, create } from 'react-test-renderer';
import { useColorScheme } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { ThemeProvider } from '@/theme';
import TabLayout from '@/app/(tabs)/_layout';

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
    options?: { title?: string; tabBarAccessibilityLabel?: string };
  }) =>
    React.createElement(
      View,
      { testID: `tab-screen-${name}` },
      React.createElement(Text, {}, options?.title ?? name),
    );

  const MockTabs = ({
    children,
    screenOptions,
  }: {
    children: React.ReactNode;
    screenOptions?: {
      headerRight?: () => React.ReactNode;
      [key: string]: unknown;
    };
  }) => {
    // Invoke headerRight so GearButton is included in the rendered tree
    const headerRight = screenOptions?.headerRight ? screenOptions.headerRight() : null;
    return React.createElement(
      View,
      { testID: 'tabs-container' },
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

  it('renders a tab-screen for "log" with title "Log"', () => {
    const tree = mount();
    const node = tree.root.find((n) => n.props.testID === 'tab-screen-log');
    expect(node).toBeTruthy();
    const textNode = node.find(
      (n) => (n.type as unknown as string) === 'Text' && n.props.children === 'Log',
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
    const knownScreens = ['index', 'log', 'trends'];
    const unexpectedScreens = tree.root.findAll(
      (n) =>
        typeof n.props.testID === 'string' &&
        n.props.testID.startsWith('tab-screen-') &&
        !knownScreens.some((name) => n.props.testID === `tab-screen-${name}`),
    );
    expect(unexpectedScreens).toHaveLength(0);
  });

  it('renders the gear button with accessibilityLabel="Open profile"', () => {
    const tree = mount();
    const gearButton = tree.root.find(
      (n) => n.props.accessibilityLabel === 'Open profile',
    );
    expect(gearButton).toBeTruthy();
  });
});
