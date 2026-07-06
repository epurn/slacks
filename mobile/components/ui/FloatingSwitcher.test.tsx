import { StyleSheet } from 'react-native';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import {
  FLOATING_SWITCHER_HEIGHT,
  FloatingSwitcher,
  floatingSwitcherClearance,
  type FloatingSwitcherSegment,
} from './FloatingSwitcher';
import { ThemeProvider } from '@/theme';

// Stub the native blur so the pill renders without the native module; expose the
// tint so the light/dark material can be asserted.
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

// Stub SF Symbols so the requested glyph name is assertable via testID.
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

const SEGMENTS: readonly FloatingSwitcherSegment[] = [
  { key: 'index', label: 'Today', icon: 'sun.max' },
  { key: 'trends', label: 'Trends', icon: 'chart.line.uptrend.xyaxis' },
];

function renderSwitcher(
  override: 'light' | 'dark',
  activeKey: string,
  onSelect: (key: string) => void = jest.fn(),
): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 390, height: 844 },
          insets: { top: 47, left: 0, right: 0, bottom: 34 },
        }}
      >
        <ThemeProvider override={override}>
          <FloatingSwitcher segments={SEGMENTS} activeKey={activeKey} onSelect={onSelect} />
        </ThemeProvider>
      </SafeAreaProvider>,
    );
  });
  return tree;
}

function segment(tree: ReactTestRenderer, key: string) {
  return tree.root.find((n) => n.props.testID === `floating-switcher-${key}`);
}

describe('FloatingSwitcher (FTY-242)', () => {
  it('renders both destinations with their SF Symbol, label, and a >=44pt target', () => {
    const tree = renderSwitcher('light', 'index');

    for (const seg of SEGMENTS) {
      const node = segment(tree, seg.key);
      expect(node).toBeTruthy();

      // The correct SF Symbol glyph is requested.
      expect(node.find((n) => n.props.testID === `sf-symbol-${seg.icon}`)).toBeTruthy();

      // The visible text label renders.
      const text = node.find(
        (n) =>
          (n.type as unknown as string) === 'Text' && n.props.children === seg.label,
      );
      expect(text).toBeTruthy();

      // ≥44pt accessible press target.
      const flat = StyleSheet.flatten(node.props.style) as {
        minHeight?: number;
        minWidth?: number;
      };
      expect(flat.minWidth).toBeGreaterThanOrEqual(44);
    }
  });

  it('marks the active segment selected and the other not (VoiceOver)', () => {
    const tree = renderSwitcher('light', 'trends');

    const today = segment(tree, 'index');
    const trends = segment(tree, 'trends');

    expect(today.props.accessibilityRole).toBe('button');
    expect(today.props.accessibilityLabel).toBe('Today');
    expect(today.props.accessibilityState).toEqual({ selected: false });

    expect(trends.props.accessibilityLabel).toBe('Trends');
    expect(trends.props.accessibilityState).toEqual({ selected: true });
  });

  it('calls onSelect with the tapped segment key', () => {
    const onSelect = jest.fn();
    const tree = renderSwitcher('light', 'index', onSelect);

    act(() => {
      segment(tree, 'trends').props.onPress();
    });
    expect(onSelect).toHaveBeenCalledWith('trends');

    act(() => {
      segment(tree, 'index').props.onPress();
    });
    expect(onSelect).toHaveBeenCalledWith('index');
  });

  it('uses the light/dark system blur material', () => {
    const light = renderSwitcher('light', 'index');
    expect(
      light.root.find((n) => n.props.testID === 'switcher-blur').props.tint,
    ).toBe('systemChromeMaterialLight');

    const dark = renderSwitcher('dark', 'index');
    expect(
      dark.root.find((n) => n.props.testID === 'switcher-blur').props.tint,
    ).toBe('systemChromeMaterialDark');
  });

  it('anchors bottom-left above the home indicator', () => {
    const tree = renderSwitcher('light', 'index');
    const anchor = tree.root.find((n) => n.props.testID === 'floating-switcher');
    const flat = StyleSheet.flatten(anchor.props.style) as {
      position?: string;
      left?: number;
      bottom?: number;
    };
    expect(flat.position).toBe('absolute');
    expect(flat.left).toBe(16);
    // 34 (safe-area bottom) + gap → clears the home indicator.
    expect(flat.bottom).toBeGreaterThan(34);
  });
});

describe('floatingSwitcherClearance', () => {
  it('reserves the switcher footprint above the safe-area bottom', () => {
    const bottomInset = 34;
    const clearance = floatingSwitcherClearance(bottomInset);
    // Strictly more than the bare inset plus the pill height, so the last row
    // clears both the home indicator and the pill.
    expect(clearance).toBeGreaterThanOrEqual(bottomInset + FLOATING_SWITCHER_HEIGHT);
    expect(clearance).toBeGreaterThan(bottomInset);
  });
});
