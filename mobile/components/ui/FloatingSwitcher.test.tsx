import { Animated, StyleSheet } from 'react-native';
import { act, create, type ReactTestRenderer } from 'react-test-renderer';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import {
  FLOATING_SWITCHER_BOTTOM_GAP,
  FLOATING_SWITCHER_HEIGHT,
  FloatingSwitcher,
  floatingSwitcherClearance,
  type FloatingSwitcherSegment,
} from './FloatingSwitcher';
import { spacing, ThemeProvider } from '@/theme';
import { mockReduceMotion } from '@/testUtils/reduceMotion';

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

// Reduce Motion off by default so the capsule takes its spring path; specific
// tests below override this to exercise the Reduce Motion branch.
beforeEach(() => {
  mockReduceMotion(false);
});

afterEach(() => {
  jest.restoreAllMocks();
});

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

function updateSwitcher(
  tree: ReactTestRenderer,
  override: 'light' | 'dark',
  activeKey: string,
  onSelect: (key: string) => void = jest.fn(),
): void {
  act(() => {
    tree.update(
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
}

// react-test-renderer never fires real `onLayout` events, so tests that need
// measured segment bounds (the sliding capsule) trigger them by hand with
// synthetic — but realistically shaped — layout rectangles.
function layoutSegments(tree: ReactTestRenderer): void {
  act(() => {
    segment(tree, 'index').props.onLayout({
      nativeEvent: { layout: { x: 4, y: 4, width: 92, height: 44 } },
    });
  });
  act(() => {
    segment(tree, 'trends').props.onLayout({
      nativeEvent: { layout: { x: 100, y: 4, width: 98, height: 44 } },
    });
  });
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

      // ≥44pt accessible press target. `style` is the pressed-state function
      // form (FTY-323); resolve it for the unpressed state to get the layout.
      const flat = StyleSheet.flatten(node.props.style({ pressed: false })) as {
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
  // Footprint = gap beneath the pill + pill height + one breathing step above,
  // i.e. everything the clearance reserves on top of the safe-area bottom.
  const footprint = FLOATING_SWITCHER_BOTTOM_GAP + FLOATING_SWITCHER_HEIGHT + spacing.lg;

  it('equals the pill footprint plus the safe-area bottom exactly', () => {
    const bottomInset = 34;
    // Exact contract (not a loose lower bound): footprint + safe-area bottom, so
    // a downstream screen reserving this value clears the pill and no more.
    expect(floatingSwitcherClearance(bottomInset)).toBe(bottomInset + footprint);
    // Pinned numerics so a silent change to any footprint constant trips here.
    expect(footprint).toBe(80);
    expect(floatingSwitcherClearance(bottomInset)).toBe(114);
  });

  it('is a positive number equal to the footprint when there is no home indicator', () => {
    expect(floatingSwitcherClearance(0)).toBe(footprint);
    expect(floatingSwitcherClearance(0)).toBeGreaterThan(0);
  });
});

describe('FloatingSwitcher — pressed feedback (FTY-323)', () => {
  it('dims the pressed segment with a calm opacity — no white flash, scale, or ripple', () => {
    const tree = renderSwitcher('light', 'index');
    const node = segment(tree, 'trends');

    // `style` is the pressed-state function form; RN never invokes it in
    // react-test-renderer, so the test calls it directly with both states.
    expect(typeof node.props.style).toBe('function');
    const rest = StyleSheet.flatten(node.props.style({ pressed: false })) as Record<
      string,
      unknown
    >;
    const pressed = StyleSheet.flatten(node.props.style({ pressed: true })) as Record<
      string,
      unknown
    >;

    expect(pressed.opacity).toBeLessThan(1);
    expect(rest.opacity).not.toBe(pressed.opacity);
    // No scale transform, no background swap, no Android ripple — a quiet dim
    // is the whole effect, matching EntryRow/ItemTimelineRow's pressed idiom.
    expect(pressed.transform).toBeUndefined();
    expect(pressed.backgroundColor).toBeUndefined();
    expect(node.props.android_ripple).toBeUndefined();
  });
});

describe('FloatingSwitcher — active capsule motion (FTY-323)', () => {
  const FAKE_ANIM = {
    start: (cb?: (r: { finished: boolean }) => void) => cb?.({ finished: true }),
    stop: () => {},
  };
  let springSpy: jest.SpyInstance;

  beforeEach(() => {
    springSpy = jest.spyOn(Animated, 'spring').mockReturnValue(FAKE_ANIM as never);
  });

  it('snaps into place on initial layout — no spring on mount', () => {
    const tree = renderSwitcher('light', 'index');
    layoutSegments(tree);

    expect(springSpy).not.toHaveBeenCalled();

    const capsule = tree.root.find((n) => n.props.testID === 'floating-switcher-capsule');
    const flat = StyleSheet.flatten(capsule.props.style) as { left?: unknown; width?: unknown };
    expect((flat.left as { __getValue?: () => number }).__getValue?.()).toBe(4);
    expect((flat.width as { __getValue?: () => number }).__getValue?.()).toBe(92);
  });

  it('animates the capsule across with Animated.spring when the active segment changes', () => {
    const tree = renderSwitcher('light', 'index');
    layoutSegments(tree);
    springSpy.mockClear();

    updateSwitcher(tree, 'light', 'trends');

    expect(springSpy).toHaveBeenCalled();
    // Both axes (position and width) animate, since the two labels differ in width.
    expect(springSpy.mock.calls.some((call) => call[1]?.toValue === 100)).toBe(true);
    expect(springSpy.mock.calls.some((call) => call[1]?.toValue === 98)).toBe(true);
    // Springs the raised capsule with useNativeDriver: false (left/width can't
    // run on the native driver) using the shared short-spring config.
    expect(springSpy.mock.calls.every((call) => call[1]?.useNativeDriver === false)).toBe(true);
  });

  it('a re-layout of the still-active segment (Dynamic Type) snaps without a spring', () => {
    const tree = renderSwitcher('light', 'index');
    layoutSegments(tree);
    springSpy.mockClear();

    act(() => {
      segment(tree, 'index').props.onLayout({
        nativeEvent: { layout: { x: 4, y: 4, width: 110, height: 44 } },
      });
    });

    expect(springSpy).not.toHaveBeenCalled();
  });

  it('Reduce Motion: swaps the capsule position instantly instead of springing', () => {
    mockReduceMotion(true);
    const tree = renderSwitcher('light', 'index');
    layoutSegments(tree);
    springSpy.mockClear();

    updateSwitcher(tree, 'light', 'trends');

    expect(springSpy).not.toHaveBeenCalled();
    const capsule = tree.root.find((n) => n.props.testID === 'floating-switcher-capsule');
    const flat = StyleSheet.flatten(capsule.props.style) as { left?: unknown; width?: unknown };
    expect((flat.left as { __getValue?: () => number }).__getValue?.()).toBe(100);
    expect((flat.width as { __getValue?: () => number }).__getValue?.()).toBe(98);
  });
});
