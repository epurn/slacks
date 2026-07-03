import { useCallback, useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated } from 'react-native';

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

/**
 * Live "is Reduce Motion enabled" for the signature beats. Mirrors the Skeleton
 * pattern: read `AccessibilityInfo.isReduceMotionEnabled()` once and subscribe to
 * `reduceMotionChanged` so a mid-session toggle is honoured.
 *
 * Until the async read resolves (or if it rejects) the value is treated as **on**
 * (`true`) — the calm default, so a beat never flashes spring motion at a user who
 * may have opted out before the setting is known.
 */
export function useReduceMotion(): boolean {
  // `null` (still resolving) degrades to the no-motion path.
  return useReduceMotionState() !== false;
}

/**
 * The raw Reduce Motion state: `null` while the async read is in flight, then the
 * live boolean. Callers that must not pick a motion branch before the setting is
 * known (e.g. the resolve fade, which plays exactly once) read the nullable form;
 * most callers use {@link useReduceMotion}, which coalesces `null` to "on".
 */
export function useReduceMotionState(): boolean | null {
  const [reduceMotion, setReduceMotion] = useState<boolean | null>(null);

  useEffect(() => {
    let mounted = true;
    AccessibilityInfo.isReduceMotionEnabled().then(
      (enabled) => {
        if (mounted) setReduceMotion(enabled);
      },
      () => {
        if (mounted) setReduceMotion(true);
      },
    );
    const subscription = AccessibilityInfo.addEventListener(
      'reduceMotionChanged',
      (enabled) => setReduceMotion(enabled),
    );
    return () => {
      mounted = false;
      // Defensive: a stubbed AccessibilityInfo may not return a subscription.
      subscription?.remove?.();
    };
  }, []);

  return reduceMotion;
}

/**
 * A one-shot "gentle pulse" beat (target reached, correction saved). Returns an
 * animated `scale`/`opacity` pair to spread onto the pulsing view and a `pulse()`
 * trigger. Normally a short spring scale bump (`defaultSpring`); under Reduce
 * Motion the pulse degrades to a brief opacity fade — no motion.
 */
export function usePulse(): {
  scale: Animated.Value;
  opacity: Animated.Value;
  pulse: () => void;
} {
  const reduceMotion = useReduceMotion();
  // Held in state (via lazy initializer) so the Animated.Value is created once and
  // is stable across renders — the RN-idiomatic alternative to a ref that the
  // "no refs during render" lint rule allows.
  const [scale] = useState(() => new Animated.Value(1));
  const [opacity] = useState(() => new Animated.Value(1));

  const pulse = useCallback(() => {
    if (reduceMotion) {
      // Simple fade — no scale/translate motion for opted-out users.
      opacity.setValue(1);
      Animated.sequence([
        Animated.timing(opacity, {
          toValue: 0.55,
          duration: reducedMotionDuration / 2,
          useNativeDriver: true,
        }),
        Animated.timing(opacity, {
          toValue: 1,
          duration: reducedMotionDuration / 2,
          useNativeDriver: true,
        }),
      ]).start();
      return;
    }
    scale.setValue(1);
    Animated.sequence([
      Animated.spring(scale, { ...defaultSpring, toValue: 1.04 }),
      Animated.spring(scale, { ...defaultSpring, toValue: 1 }),
    ]).start();
  }, [reduceMotion, scale, opacity]);

  return { scale, opacity, pulse };
}

/**
 * Fade-in for the entry-resolve beat (shimmer → value). Returns an animated
 * `opacity` for the resolved value's row. When `active` first becomes true the
 * value eases in with `gentleSpring`; under Reduce Motion it is a simple timing
 * fade. The fade plays once — a static (already-resolved) row stays fully opaque
 * and never re-animates on re-render.
 */
export function useResolveFade(active: boolean): Animated.Value {
  // Nullable form: the fade plays once, so it must wait for the setting to be
  // known before choosing spring-vs-fade — otherwise every resolve would take the
  // fallback fade before the read settles.
  const reduceMotion = useReduceMotionState();
  const [opacity] = useState(() => new Animated.Value(active ? 0 : 1));
  const played = useRef(false);

  useEffect(() => {
    if (!active || played.current || reduceMotion === null) return;
    played.current = true;
    opacity.setValue(0);
    if (reduceMotion) {
      Animated.timing(opacity, {
        toValue: 1,
        duration: reducedMotionDuration,
        useNativeDriver: true,
      }).start();
    } else {
      Animated.spring(opacity, { ...gentleSpring, toValue: 1 }).start();
    }
  }, [active, reduceMotion, opacity]);

  return opacity;
}
