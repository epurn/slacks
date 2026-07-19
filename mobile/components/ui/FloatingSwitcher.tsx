import { BlurView } from 'expo-blur';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  Animated,
  type LayoutChangeEvent,
  Pressable,
  StyleSheet,
  Text,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppIcon, type AppIconName } from './AppIcon';
import { spacing, radius, useTheme } from '@/theme';
import { defaultSpring, useReduceMotion } from '@/theme/motion';
import { typeScale } from '@/theme/typography';

/**
 * A single destination in the floating switcher. `key` is the Expo Router route
 * name (e.g. `index`, `trends`) so the shell can map router state ↔ segment
 * without a second source of truth.
 */
export interface FloatingSwitcherSegment {
  key: string;
  label: string;
  icon: AppIconName;
}

/** Height of the pill — comfortably above the 44pt minimum touch target. */
export const FLOATING_SWITCHER_HEIGHT = 52;

/** Gap between the pill's bottom edge and the safe-area bottom (home indicator). */
export const FLOATING_SWITCHER_BOTTOM_GAP = spacing.sm;

/**
 * Bottom clearance a scrollable screen must reserve so its last row scrolls
 * clear of the floating switcher *and* the home indicator. The single source of
 * truth for the pill's footprint, so Today and Trends can't drift from it: the
 * safe-area inset (home indicator), the pill's own height, the gap beneath it,
 * and one spacing step of breathing room above the pill.
 */
export function floatingSwitcherClearance(bottomInset: number): number {
  return (
    bottomInset + FLOATING_SWITCHER_BOTTOM_GAP + FLOATING_SWITCHER_HEIGHT + spacing.lg
  );
}

/** Measured position/width of a segment within the row, used to slide the
 *  raised active capsule underneath it. */
interface SegmentLayout {
  x: number;
  width: number;
}

/**
 * The bottom-left floating glass switcher (FTY-242) — the app's top-level
 * navigation, replacing the old full-width bottom tab bar. Inspired by the iOS 26
 * Photos chrome: a compact segmented pill of translucent blur material, a
 * hairline edge highlight, a restrained shadow, SF Symbols via `AppIcon`, and an
 * unmistakable raised-capsule selected state that glides between segments
 * (FTY-323).
 *
 * It is presentational: it takes the segment list, the active key, and an
 * `onSelect` callback. The shell (`app/(tabs)/_layout.tsx`) wires it to the Expo
 * Router navigation state via the `tabBar` render prop so navigation state, deep
 * links, and screen ownership stay owned by the router.
 *
 * Anchored bottom-left with `position: absolute` so it contributes no layout
 * height to the tab-bar slot — the scene draws full-screen and the pill floats
 * over it (the modern full-screen shell). Safe-area insets keep it above the home
 * indicator; `box-none` lets touches outside the pill fall through to content.
 */
export function FloatingSwitcher({
  segments,
  activeKey,
  onSelect,
}: {
  segments: readonly FloatingSwitcherSegment[];
  activeKey: string;
  onSelect: (key: string) => void;
}) {
  const { colors, isDark } = useTheme();
  const insets = useSafeAreaInsets();
  const reduceMotion = useReduceMotion();

  // The raised active capsule is a single element that slides under whichever
  // segment is active, rather than a background style toggled per-segment —
  // that's what lets it glide (FTY-323) instead of jump-cutting.
  //
  // The transit is driven purely by transforms (`translateX` + `scaleX`) so it
  // can run on the native driver (FTY-387): the capsule's box is fixed at a
  // static `left: 0` / `width: baseWidth`, and every segment position is reached
  // by translating + scaling that box on the UI thread. Animating `left`/`width`
  // instead would force the spring onto the JS thread, where the heavy first
  // Trends mount stalls it and the glide degrades to a jump cut exactly when a
  // new user first sees it. `baseWidth` is the width of the first measured active
  // segment; all transforms are expressed relative to it and its centre.
  const [segmentLayouts, setSegmentLayouts] = useState<Record<string, SegmentLayout>>({});
  const [baseWidth, setBaseWidth] = useState(0);
  const [translateX] = useState(() => new Animated.Value(0));
  const [scaleX] = useState(() => new Animated.Value(1));
  const hasPositioned = useRef(false);
  const prevActiveKey = useRef(activeKey);

  const handleSegmentLayout = useCallback(
    (key: string, event: LayoutChangeEvent) => {
      const { x, width } = event.nativeEvent.layout;
      setSegmentLayouts((prev) => {
        const existing = prev[key];
        if (existing && existing.x === x && existing.width === width) return prev;
        return { ...prev, [key]: { x, width } };
      });
      // Pin the capsule's static box to the first measured active segment. All
      // transforms are expressed relative to this base, so the box never
      // re-renders again and the transit stays purely transform-driven.
      if (key === activeKey) setBaseWidth((prev) => (prev === 0 ? width : prev));
    },
    [activeKey],
  );

  useEffect(() => {
    const target = segmentLayouts[activeKey];
    if (!target || baseWidth === 0) return;

    // Map the measured segment rect onto the fixed base box `[0, baseWidth]`
    // (centre at baseWidth/2): scaleX matches the target width; translateX moves
    // the (scaled) centre to the target's centre. RN scales around the view
    // centre and applies the outer translate in unscaled pixels, so the rendered
    // rect lands exactly on `[target.x, target.x + target.width]`.
    const tx = target.x + target.width / 2 - baseWidth / 2;
    const s = target.width / baseWidth;

    const firstPosition = !hasPositioned.current;
    const selectionChanged = !firstPosition && prevActiveKey.current !== activeKey;
    prevActiveKey.current = activeKey;
    hasPositioned.current = true;

    if (firstPosition || !selectionChanged || reduceMotion) {
      // First measurement snaps into place (no animate-in from the origin); a
      // re-layout of the same segment (Dynamic Type, rotation) snaps in place;
      // Reduce Motion degrades the selection change to an instant swap — no
      // spring.
      translateX.setValue(tx);
      scaleX.setValue(s);
      return;
    }

    // Native-driver transit: the transform springs run on the UI thread, so the
    // glide is visible even while the first Trends mount stalls the JS thread.
    Animated.spring(translateX, { ...defaultSpring, toValue: tx, useNativeDriver: true }).start();
    Animated.spring(scaleX, { ...defaultSpring, toValue: s, useNativeDriver: true }).start();
  }, [activeKey, segmentLayouts, reduceMotion, baseWidth, translateX, scaleX]);

  return (
    <View
      testID="floating-switcher"
      pointerEvents="box-none"
      style={[
        styles.anchor,
        { left: spacing.base, bottom: insets.bottom + FLOATING_SWITCHER_BOTTOM_GAP },
      ]}
    >
      <View
        style={[
          styles.pill,
          {
            borderColor: colors.switcherBorder,
            shadowColor: '#000000',
            // Dark canvas swallows a black shadow almost entirely, so the pill
            // leans harder on elevation there to keep reading as raised.
            shadowOpacity: isDark ? 0.45 : 0.16,
            shadowRadius: isDark ? 18 : 12,
          },
        ]}
      >
        {/* Real system blur material — the glass. */}
        <BlurView
          tint={isDark ? 'systemChromeMaterialDark' : 'systemChromeMaterialLight'}
          intensity={60}
          style={StyleSheet.absoluteFill}
        />
        {/* Token-sourced translucent fallback over the blur so the pill stays
            legible where the native blur is weak or unsupported. */}
        <View
          pointerEvents="none"
          style={[StyleSheet.absoluteFill, { backgroundColor: colors.switcherGlass }]}
        />

        <View style={styles.row}>
          <Animated.View
            testID="floating-switcher-capsule"
            pointerEvents="none"
            style={[
              styles.activeCapsule,
              {
                left: 0,
                width: baseWidth,
                transform: [{ translateX }, { scaleX }],
                backgroundColor: colors.surfaceRaised,
                borderColor: colors.switcherBorder,
                shadowColor: '#000000',
              },
            ]}
          />
          {segments.map((seg) => {
            const active = seg.key === activeKey;
            const tint = active ? colors.tabActive : colors.tabInactive;
            return (
              <Pressable
                key={seg.key}
                testID={`floating-switcher-${seg.key}`}
                accessibilityRole="button"
                accessibilityState={{ selected: active }}
                accessibilityLabel={seg.label}
                onPress={() => onSelect(seg.key)}
                onLayout={(event) => handleSegmentLayout(seg.key, event)}
                style={({ pressed }) => [styles.segment, pressed && styles.segmentPressed]}
              >
                <AppIcon name={seg.icon} size={18} color={tint} />
                <Text
                  numberOfLines={1}
                  style={[
                    styles.label,
                    { color: tint, fontWeight: active ? '600' : '500' },
                  ]}
                >
                  {seg.label}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  anchor: {
    position: 'absolute',
  },
  pill: {
    flexDirection: 'row',
    borderRadius: radius.full,
    borderWidth: StyleSheet.hairlineWidth,
    overflow: 'hidden',
    // Restrained elevation — present but not a heavy drop shadow.
    shadowOpacity: 0.16,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 6 },
    elevation: 8,
  },
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    padding: spacing.xs,
    gap: spacing.xs,
  },
  // The sliding active-capsule background — positioned absolutely within `row`
  // with a fixed box, then translated + scaled on the native driver to the
  // measured bounds of the active segment, so selecting the other segment
  // glides the capsule across (FTY-323) on the UI thread (FTY-387) instead of
  // jump-cutting a per-segment background.
  activeCapsule: {
    position: 'absolute',
    top: 0,
    bottom: 0,
    borderRadius: radius.full,
    borderWidth: StyleSheet.hairlineWidth,
    shadowOpacity: 0.12,
    shadowRadius: 3,
    shadowOffset: { width: 0, height: 1 },
    elevation: 2,
  },
  segment: {
    minHeight: FLOATING_SWITCHER_HEIGHT - spacing.xs * 2,
    minWidth: 44,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    borderRadius: radius.full,
  },
  // Calm pressed feedback — a quiet opacity dim (matches EntryRow/
  // ItemTimelineRow), never a white flash, scale, or ripple.
  segmentPressed: {
    opacity: 0.6,
  },
  label: {
    fontSize: typeScale.footnote,
  },
});
