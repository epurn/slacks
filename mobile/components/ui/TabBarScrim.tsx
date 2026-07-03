import { useMemo } from 'react';
import { StyleSheet, View } from 'react-native';

import { useTheme } from '@/theme';

/** Number of stacked bands used to approximate the fade gradient. */
const BAND_COUNT = 12;

/**
 * A vertical fade/scrim that dims scrolled content as it slides beneath the
 * floating, blurred tab bar (FTY-185).
 *
 * expo-blur's material is a native effect that the JS/Maestro harness cannot
 * observe, and a blur alone does not guarantee the story's requirement — that
 * scrolled timeline text "fades/dims beneath the bar" and "is not legible
 * through the tab labels." High-contrast content can still read through a thin
 * `.ultraThin` material. This overlay renders a real, app-drawn dimming gradient
 * — fully transparent at the top, ramping to the opaque screen `surface` colour
 * at the bottom — so content visibly fades into the surface before it reaches
 * the tab labels, independent of the native blur, and the fade is
 * machine-assertable.
 *
 * React Native ships no gradient primitive and the SDK pins no gradient
 * dependency, so the gradient is approximated with a stack of equal-height bands
 * whose `surface`-colour opacity ramps linearly from 0 (top, content fully
 * legible) to 1 (bottom, content faded fully into the surface). It is absolutely
 * pinned to the bottom of the screen and `pointerEvents="none"`, so it never
 * intercepts touches or scrolling; it paints above the scroll content and
 * beneath the navigator's tab bar.
 */
export function TabBarScrim({ height }: { height: number }) {
  const { colors } = useTheme();

  const bands = useMemo(
    () =>
      Array.from({ length: BAND_COUNT }, (_, i) => ({
        key: i,
        // 0 at the top (content fully legible) → 1 at the bottom (content faded
        // fully into the surface, so nothing reads through the tab labels).
        opacity: i / (BAND_COUNT - 1),
      })),
    [],
  );

  return (
    <View
      testID="tab-bar-scrim"
      pointerEvents="none"
      style={[styles.container, { height }]}
    >
      {bands.map((band) => (
        <View
          key={band.key}
          testID={`tab-bar-scrim-band-${band.key}`}
          style={[
            styles.band,
            { backgroundColor: colors.surface, opacity: band.opacity },
          ]}
        />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: 'absolute',
    left: 0,
    right: 0,
    bottom: 0,
  },
  band: {
    flex: 1,
  },
});
