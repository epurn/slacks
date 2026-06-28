import { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, StyleSheet, View, type DimensionValue, type ViewProps } from 'react-native';
import { useTheme } from '@/theme';

interface SkeletonProps extends ViewProps {
  width?: DimensionValue;
  height?: number;
  borderRadius?: number;
}

/**
 * Skeleton / shimmer placeholder for the "thinking" loading state.
 *
 * The shimmer animation fills the placeholder in place so resolved content
 * arrives without layout shift. Under the system Reduce Motion setting the
 * shimmer degrades to a static placeholder — no animation is forced on
 * users who have opted out.
 *
 * The Animated.Value is stored in a ref per the React Native Animated API
 * contract. The eslint-disable comments below acknowledge that Animated.Value
 * refs are legitimately accessed during render for interpolation — this is the
 * documented RN pattern and does not cause stale-closure issues because
 * Animated.Value is a mutable reference type, not a primitive.
 */
export function Skeleton({
  width = '100%',
  height = 20,
  borderRadius = 6,
  style,
  ...rest
}: SkeletonProps) {
  const { colors, isDark } = useTheme();
  // eslint-disable-next-line react-hooks/refs
  const shimmer = useRef(new Animated.Value(0)).current;
  // `null` until the async Reduce Motion check resolves, then the live value.
  // Held in state (not a ref) so the animation effect below re-runs once the
  // setting is known and whenever the user toggles it — a ref would resolve
  // after the loop had already started and never re-trigger it.
  const [reduceMotion, setReduceMotion] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    AccessibilityInfo.isReduceMotionEnabled().then((enabled) => {
      if (mounted) setReduceMotion(enabled);
    });
    const subscription = AccessibilityInfo.addEventListener(
      'reduceMotionChanged',
      (enabled) => setReduceMotion(enabled),
    );
    return () => {
      mounted = false;
      subscription.remove();
    };
  }, []);

  useEffect(() => {
    // Animate only once we know Reduce Motion is off. While unknown (`null`) or
    // enabled, leave the placeholder static — never force motion on opt-out.
    if (reduceMotion !== false) {
      shimmer.setValue(0);
      return;
    }

    const loop = Animated.loop(
      Animated.sequence([
        Animated.timing(shimmer, {
          toValue: 1,
          duration: 900,
          useNativeDriver: true,
        }),
        Animated.timing(shimmer, {
          toValue: 0,
          duration: 900,
          useNativeDriver: true,
        }),
      ]),
    );
    loop.start();
    return () => loop.stop();
  }, [shimmer, reduceMotion]);

  // eslint-disable-next-line react-hooks/refs
  const opacity = shimmer.interpolate({
    inputRange: [0, 1],
    outputRange: isDark ? [0.18, 0.35] : [0.12, 0.28],
  });

  const base = isDark ? '#FFFFFF' : '#000000';

  return (
    <View
      accessibilityLabel="Loading"
      accessibilityRole="progressbar"
      style={[{ width, height, borderRadius, overflow: 'hidden' }, style]}
      {...rest}
    >
      <View
        style={[
          StyleSheet.absoluteFill,
          { backgroundColor: colors.separator },
        ]}
      />
      <Animated.View
        style={[
          StyleSheet.absoluteFill,
          { backgroundColor: base, opacity },
        ]}
      />
    </View>
  );
}
