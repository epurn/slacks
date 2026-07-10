import React from 'react';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import TabLayout from '@/app/(tabs)/_layout';
import { ThemeProvider } from '@/theme';
import {
  cleanupReactTestRenderers,
  trackReactTestRenderer,
} from '@/testUtils/reactTestRenderer';
import { mockReduceMotion } from '@/testUtils/reduceMotion';

// ---------------------------------------------------------------------------
// Capture the props the layout hands to expo-router's `Tabs` — the global
// `screenOptions`, the custom `tabBar` render prop (the floating switcher), and
// each registered `Tabs.Screen` name — so the shell contract can be asserted
// without a live navigation runtime.
// ---------------------------------------------------------------------------

let capturedScreenOptions: Record<string, unknown> | undefined;
let capturedTabBar:
  | ((props: {
      state: { index: number; routes: { key: string; name: string }[] };
      navigation: {
        emit: (e: unknown) => { defaultPrevented: boolean };
        navigate: (name: string) => void;
      };
    }) => React.ReactNode)
  | undefined;
let mockRegisteredScreens: string[] = [];

jest.mock('expo-router', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require('react');
  const Tabs = ({
    screenOptions,
    tabBar,
    children,
  }: {
    screenOptions: Record<string, unknown>;
    tabBar: (props: unknown) => React.ReactNode;
    children: React.ReactNode;
  }) => {
    capturedScreenOptions = screenOptions;
    capturedTabBar = tabBar as typeof capturedTabBar;
    return ReactLib.createElement(ReactLib.Fragment, null, children);
  };
  Tabs.Screen = function TabsScreen({ name }: { name: string }) {
    mockRegisteredScreens.push(name);
    return null;
  };
  return { Tabs };
});

jest.mock('expo-blur', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactNative = require('react-native');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require('react');
  return {
    BlurView: (props: Record<string, unknown>) =>
      ReactLib.createElement(ReactNative.View, { testID: 'switcher-blur', ...props }),
  };
});

jest.mock('expo-symbols', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactNative = require('react-native');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require('react');
  return {
    SymbolView: ({ name }: { name: string }) =>
      ReactLib.createElement(ReactNative.View, { testID: `sf-symbol-${String(name)}` }),
  };
});

function renderLayout(): void {
  capturedScreenOptions = undefined;
  capturedTabBar = undefined;
  mockRegisteredScreens = [];
  act(() => {
    trackReactTestRenderer(
      create(
        <ThemeProvider override="light">
          <TabLayout />
        </ThemeProvider>,
      ),
    );
  });
}

/** Mount the captured `tabBar` render prop (the floating switcher) for a state. */
function renderSwitcher(
  activeIndex: number,
  navigation: {
    emit: (e: unknown) => { defaultPrevented: boolean };
    navigate: (name: string) => void;
  },
): ReactTestRenderer {
  const state = {
    index: activeIndex,
    routes: [
      { key: 'index-key', name: 'index' },
      { key: 'trends-key', name: 'trends' },
    ],
  };
  let tree!: ReactTestRenderer;
  act(() => {
    tree = trackReactTestRenderer(
      create(
        <SafeAreaProvider
          initialMetrics={{
            frame: { x: 0, y: 0, width: 390, height: 844 },
            insets: { top: 47, left: 0, right: 0, bottom: 34 },
          }}
        >
          <ThemeProvider override="light">
            {capturedTabBar!({ state, navigation }) as React.ReactElement}
          </ThemeProvider>
        </SafeAreaProvider>,
      ),
    );
  });
  return tree;
}

beforeEach(() => {
  mockReduceMotion(false);
});

afterEach(() => {
  cleanupReactTestRenderers();
  jest.restoreAllMocks();
});

describe('TabLayout shell (FTY-242 floating switcher)', () => {
  it('suppresses the native header globally', () => {
    renderLayout();
    expect(capturedScreenOptions?.headerShown).toBe(false);
  });

  it('exposes exactly two destinations — Today (index) and Trends (trends), no Log', () => {
    renderLayout();
    expect(mockRegisteredScreens.sort()).toEqual(['index', 'trends']);
    expect(mockRegisteredScreens).not.toContain('log');
  });

  it('no longer configures a full-width tab-bar background or scrim contract', () => {
    renderLayout();
    // The retired FTY-185/FTY-218 full-width tab-bar chrome: a `tabBarBackground`
    // BlurView, an absolute `tabBarStyle`, and the tab-bar scrim. None survive.
    expect(capturedScreenOptions).not.toHaveProperty('tabBarBackground');
    expect(capturedScreenOptions).not.toHaveProperty('tabBarStyle');
    // Navigation is a custom `tabBar` render prop instead.
    expect(typeof capturedTabBar).toBe('function');
  });

  it('renders the floating switcher with both segments and their SF Symbols', () => {
    renderLayout();
    const tree = renderSwitcher(0, {
      emit: () => ({ defaultPrevented: false }),
      navigate: jest.fn(),
    });

    expect(tree.root.find((n) => n.props.testID === 'floating-switcher')).toBeTruthy();
    expect(tree.root.find((n) => n.props.testID === 'floating-switcher-index')).toBeTruthy();
    expect(tree.root.find((n) => n.props.testID === 'floating-switcher-trends')).toBeTruthy();
    expect(tree.root.find((n) => n.props.testID === 'sf-symbol-sun.max')).toBeTruthy();
    expect(
      tree.root.find((n) => n.props.testID === 'sf-symbol-chart.line.uptrend.xyaxis'),
    ).toBeTruthy();
  });

  it('marks the focused route as the selected segment', () => {
    renderLayout();
    const tree = renderSwitcher(1, {
      emit: () => ({ defaultPrevented: false }),
      navigate: jest.fn(),
    });
    const trends = tree.root.find((n) => n.props.testID === 'floating-switcher-trends');
    const today = tree.root.find((n) => n.props.testID === 'floating-switcher-index');
    expect(trends.props.accessibilityState).toEqual({ selected: true });
    expect(today.props.accessibilityState).toEqual({ selected: false });
  });

  it('navigates to the tapped destination via a tabPress event', () => {
    renderLayout();
    const emit = jest.fn(() => ({ defaultPrevented: false }));
    const navigate = jest.fn();
    const tree = renderSwitcher(0, { emit, navigate });

    act(() => {
      tree.root.find((n) => n.props.testID === 'floating-switcher-trends').props.onPress();
    });

    expect(emit).toHaveBeenCalledWith(
      expect.objectContaining({ type: 'tabPress', target: 'trends-key' }),
    );
    expect(navigate).toHaveBeenCalledWith('trends');
  });

  it('does not re-navigate when the already-focused segment is tapped', () => {
    renderLayout();
    const emit = jest.fn(() => ({ defaultPrevented: false }));
    const navigate = jest.fn();
    const tree = renderSwitcher(0, { emit, navigate });

    act(() => {
      tree.root.find((n) => n.props.testID === 'floating-switcher-index').props.onPress();
    });
    // tabPress still fires (scroll-to-top semantics) but no navigation occurs.
    expect(navigate).not.toHaveBeenCalled();
  });

  it('respects a prevented tabPress (no navigation)', () => {
    renderLayout();
    const emit = jest.fn(() => ({ defaultPrevented: true }));
    const navigate = jest.fn();
    const tree = renderSwitcher(0, { emit, navigate });

    act(() => {
      tree.root.find((n) => n.props.testID === 'floating-switcher-trends').props.onPress();
    });
    expect(navigate).not.toHaveBeenCalled();
  });
});
