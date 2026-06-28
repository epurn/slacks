import { Animated } from 'react-native';

/**
 * Default spring configuration: short, physical, restrained.
 * Matches the "quiet, physical default motion" from the design philosophy.
 */
export const defaultSpring: Omit<Animated.SpringAnimationConfig, 'toValue'> = {
  tension: 120,
  friction: 14,
  useNativeDriver: true,
};

/**
 * Gentle spring for in-place content reveals (skeleton → value).
 */
export const gentleSpring: Omit<Animated.SpringAnimationConfig, 'toValue'> = {
  tension: 80,
  friction: 12,
  useNativeDriver: true,
};

/**
 * Duration (ms) for simple fade transitions used when Reduce Motion is active.
 * Signature beats degrade to a simple fade so no motion is forced on users who
 * have opted out.
 */
export const reducedMotionDuration = 180;
