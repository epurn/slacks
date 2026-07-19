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
import {
  cleanupReactTestRenderers,
  trackReactTestRenderer,
} from '@/testUtils/reactTestRenderer';
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
  cleanupReactTestRenderers();
  jest.restoreAllMocks();
});

function renderSwitcher(
  override: 'light' | 'dark',
  activeKey: string,
  onSelect: (key: string) => void = jest.fn(),
): ReactTestRenderer {
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
          <ThemeProvider override={override}>
            <FloatingSwitcher segments={SEGMENTS} activeKey={activeKey} onSelect={onSelect} />
          </ThemeProvider>
        </SafeAreaProvider>,
      ),
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

describe('FloatingSwitcher — active capsule motion (FTY-323, native-driver FTY-387)', () => {
  const FAKE_ANIM = {
    start: (cb?: (r: { finished: boolean }) => void) => cb?.({ finished: true }),
    stop: () => {},
  };
  let springSpy: jest.SpyInstance;

  beforeEach(() => {
    springSpy = jest.spyOn(Animated, 'spring').mockReturnValue(FAKE_ANIM as never);
  });

  // The capsule box is fixed at `left: 0` / `width: baseWidth`; its resting
  // rect is reached via a `[{ translateX }, { scaleX }]` transform. Segments in
  // the fixture: index {x: 4, width: 92}, trends {x: 100, width: 98}. baseWidth
  // is the first measured active segment's width (index → 92). So the trends
  // resting transform is translateX = 100 + 98/2 - 92/2 = 103, scaleX = 98/92.
  const capsuleTransform = (tree: ReactTestRenderer) => {
    const capsule = tree.root.find((n) => n.props.testID === 'floating-switcher-capsule');
    const flat = StyleSheet.flatten(capsule.props.style) as {
      left?: number;
      width?: number;
      transform?: Array<Record<string, { __getValue?: () => number }>>;
    };
    const get = (key: 'translateX' | 'scaleX') => {
      const entry = flat.transform?.find((t) => key in t);
      return entry?.[key]?.__getValue?.();
    };
    return { left: flat.left, width: flat.width, translateX: get('translateX'), scaleX: get('scaleX') };
  };

  it('snaps into place on initial layout — no spring on mount', () => {
    const tree = renderSwitcher('light', 'index');
    layoutSegments(tree);

    expect(springSpy).not.toHaveBeenCalled();

    // The fixed box adopts the first active segment's width; the transform sits
    // at that segment's x with an identity scale — no animate-in from origin.
    const t = capsuleTransform(tree);
    expect(t.left).toBe(0);
    expect(t.width).toBe(92);
    expect(t.translateX).toBe(4);
    expect(t.scaleX).toBe(1);
  });

  it('animates the capsule across with a native-driver spring when the active segment changes', () => {
    const tree = renderSwitcher('light', 'index');
    layoutSegments(tree);
    springSpy.mockClear();

    updateSwitcher(tree, 'light', 'trends');

    expect(springSpy).toHaveBeenCalled();
    // Both axes (translate and scale) animate, since the two labels differ in width.
    expect(springSpy.mock.calls.some((call) => call[1]?.toValue === 103)).toBe(true);
    expect(springSpy.mock.calls.some((call) => call[1]?.toValue === 98 / 92)).toBe(true);
    // The selection-change transit runs on the native driver (transforms are
    // UI-thread-eligible), so it survives a JS-thread stall on the cold Trends
    // mount (FTY-387). No `left`/`width` spring remains on the selection path.
    expect(springSpy.mock.calls.every((call) => call[1]?.useNativeDriver === true)).toBe(true);
    expect(springSpy.mock.calls.every((call) => call[1]?.toValue !== 100)).toBe(true);
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
    // The base box is unchanged; the same-segment re-snap is expressed via the
    // transform (scaleX 110/92) so the resting rect still tracks the new width.
    const t = capsuleTransform(tree);
    expect(t.width).toBe(92);
    expect(t.scaleX).toBe(110 / 92);
  });

  it('Reduce Motion: swaps the capsule position instantly instead of springing', () => {
    mockReduceMotion(true);
    const tree = renderSwitcher('light', 'index');
    layoutSegments(tree);
    springSpy.mockClear();

    updateSwitcher(tree, 'light', 'trends');

    expect(springSpy).not.toHaveBeenCalled();
    const t = capsuleTransform(tree);
    expect(t.translateX).toBe(103);
    expect(t.scaleX).toBe(98 / 92);
  });
});
