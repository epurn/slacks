import { BlurView } from 'expo-blur';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { AppIcon, type AppIconName } from './AppIcon';
import { spacing, radius, useTheme } from '@/theme';
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

/**
 * The bottom-left floating glass switcher (FTY-242) — the app's top-level
 * navigation, replacing the old full-width bottom tab bar. Inspired by the iOS 26
 * Photos chrome: a compact segmented pill of translucent blur material, a
 * hairline edge highlight, a restrained shadow, SF Symbols via `AppIcon`, and an
 * unmistakable raised-capsule selected state.
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
            borderColor: colors.separator,
            shadowColor: '#000000',
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
                style={[
                  styles.segment,
                  active && {
                    backgroundColor: colors.surfaceRaised,
                    borderColor: colors.separator,
                    shadowColor: '#000000',
                  },
                  active ? styles.segmentActive : null,
                ]}
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
  segment: {
    minHeight: FLOATING_SWITCHER_HEIGHT - spacing.xs * 2,
    minWidth: 44,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'center',
    gap: spacing.xs,
    paddingHorizontal: spacing.md,
    borderRadius: radius.full,
    borderWidth: StyleSheet.hairlineWidth,
    borderColor: 'transparent',
  },
  segmentActive: {
    shadowOpacity: 0.12,
    shadowRadius: 3,
    shadowOffset: { width: 0, height: 1 },
    elevation: 2,
  },
  label: {
    fontSize: typeScale.footnote,
  },
});
