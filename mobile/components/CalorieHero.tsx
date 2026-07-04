import { useEffect, useRef, useState } from "react";
import { Animated, StyleSheet, Text, View } from "react-native";

import { useTheme, spacing, radius, typeScale } from "@/theme";
import { defaultSpring, useReduceMotion, usePulse } from "@/theme/motion";
import { targetReachedHaptic } from "@/theme/haptics";
import { ThemedNumber } from "@/components/ui";

function formatCalories(n: number): string {
  return Math.round(n).toLocaleString("en-US");
}

function pct(consumed: number, target: number): number {
  if (target <= 0) return 0;
  return Math.round((consumed / target) * 100);
}

type SummaryState = "ready" | "loading" | "unavailable";

/**
 * The Today hero: calories consumed vs. target, with a slim progress bar.
 *
 * States:
 * - Loading/unavailable summary: keeps a neutral status shell without inventing
 *   calories, target, or no-target meaning.
 * - Under budget: amber fill proportional to consumed/target, "X to go" copy.
 * - Over budget: amber fills budget portion, coral extends past it, "X over" copy.
 * - Null target: shows consumed calories with a calm "No target set" treatment.
 * - Empty (consumed = 0): shows full budget available, empty bar track.
 *
 * VoiceOver labels combine all relevant figures so the hero is fully accessible
 * by sound. Never uses color as the sole signal — over-budget is always paired
 * with "X over" text. (FTY-098)
 */
export function CalorieHero({
  consumed,
  target,
  hasIntake = true,
  summaryState = "ready",
}: {
  consumed: number;
  target: number | null;
  hasIntake?: boolean;
  summaryState?: SummaryState;
}) {
  const { colors } = useTheme();
  const reduceMotion = useReduceMotion();

  // Beat 3 — target reached. A gentle pulse + success haptic fires once when the
  // day's intake crosses the calorie target, not on every re-render while over.
  // `reachedRef` starts `null` and is seeded on the first ready render so an app
  // opened already-over-target does not buzz — only a live crossing does.
  const { scale, opacity, pulse } = usePulse();
  const reachedRef = useRef<boolean | null>(null);
  const isReadyWithTarget = summaryState === "ready" && target !== null;
  const reachedTarget =
    isReadyWithTarget && target > 0 && consumed >= target;
  useEffect(() => {
    if (!isReadyWithTarget) return;
    if (reachedRef.current === null) {
      // Seed on first known state — never a beat on mount / initial load.
      reachedRef.current = reachedTarget;
      return;
    }
    if (reachedTarget && !reachedRef.current) {
      reachedRef.current = true;
      targetReachedHaptic();
      pulse();
    } else if (!reachedTarget) {
      // Dropped back under budget: re-arm so a later crossing beats again.
      reachedRef.current = false;
    }
  }, [isReadyWithTarget, reachedTarget, pulse]);

  if (summaryState !== "ready") {
    const copy =
      summaryState === "loading"
        ? {
            context: "Loading summary",
            subLine: "Status will appear here",
            accessibilityLabel: "Daily summary loading",
          }
        : {
            context: "Summary unavailable",
            subLine: "Try again below",
            accessibilityLabel: "Daily summary unavailable",
          };

    return (
      <View
        style={[styles.container, { backgroundColor: colors.surfaceRaised }]}
        accessible={true}
        accessibilityLabel={copy.accessibilityLabel}
      >
        <ThemedNumber
          value="—"
          scale="heroDisplay"
          style={styles.heroNumber}
          accessibilityElementsHidden
        />
        <Text
          style={[styles.contextLine, { color: colors.textSecondary }]}
          accessibilityElementsHidden
        >
          {copy.context}
        </Text>
        <Text
          style={[styles.subLine, { color: colors.textMuted }]}
          accessibilityElementsHidden
        >
          {copy.subLine}
        </Text>
      </View>
    );
  }

  if (target === null) {
    return (
      <View
        style={[styles.container, { backgroundColor: colors.surfaceRaised }]}
        accessible={true}
        accessibilityLabel={`${formatCalories(consumed)} kcal today, no target set`}
      >
        <ThemedNumber
          value={formatCalories(consumed)}
          scale="heroDisplay"
          style={styles.heroNumber}
          accessibilityElementsHidden
        />
        <Text
          style={[styles.contextLine, { color: colors.textSecondary }]}
          accessibilityElementsHidden
        >
          kcal today
        </Text>
        <Text
          style={[styles.subLine, { color: colors.textMuted }]}
          accessibilityElementsHidden
        >
          No target set
        </Text>
      </View>
    );
  }

  const isOver = consumed > target;
  const remaining = Math.max(target - consumed, 0);
  const over = Math.max(consumed - target, 0);
  const percentage = pct(consumed, target);
  const isEmptyDay = !hasIntake;
  const statusLine = isEmptyDay
    ? `${formatCalories(consumed)} / ${formatCalories(target)} kcal · ${formatCalories(remaining)} to go`
    : `${formatCalories(consumed)} / ${formatCalories(target)} kcal · ${percentage}%`;

  // A11y: combine all hero data into one clear sentence.
  const a11yLabel = isOver
    ? `${formatCalories(consumed)} of ${formatCalories(target)} kcal, ${formatCalories(over)} over budget`
    : isEmptyDay
      ? `${formatCalories(consumed)} of ${formatCalories(target)} kcal, ${formatCalories(remaining)} remaining`
    : `${formatCalories(consumed)} of ${formatCalories(target)} kcal, ${percentage} percent, ${formatCalories(remaining)} remaining`;

  return (
    <Animated.View
      style={[
        styles.container,
        { backgroundColor: colors.surfaceRaised, opacity, transform: [{ scale }] },
      ]}
      accessible={true}
      accessibilityLabel={a11yLabel}
    >
      <ThemedNumber
        value={formatCalories(consumed)}
        scale="heroDisplay"
        style={styles.heroNumber}
        accessibilityElementsHidden
      />

      <Text
        style={[styles.contextLine, { color: colors.textSecondary }]}
        accessibilityElementsHidden
      >
        {statusLine}
      </Text>

      {/* Slim progress bar — eases to its value with the shared spring tokens. */}
      <ProgressBar
        consumed={consumed}
        target={target}
        isOver={isOver}
        amberColor={colors.accent}
        coralColor={colors.coral}
        trackColor={colors.separator}
        reduceMotion={reduceMotion}
      />

      {isEmptyDay ? null : (
        <Text
          style={[
            styles.subLine,
            isOver
              ? { color: colors.coral, fontWeight: "600" }
              : { color: colors.textSecondary },
          ]}
          accessibilityElementsHidden
        >
          {isOver
            ? `${formatCalories(over)} over`
            : `${formatCalories(remaining)} to go`}
        </Text>
      )}
    </Animated.View>
  );
}

/** Fill fraction (0..1) of the amber segment and, when over, the coral segment. */
function barFractions(
  consumed: number,
  target: number,
  isOver: boolean,
): { amber: number; coral: number } {
  // For over-budget the amber segment fills to the target and the coral segment
  // extends past it; the coral overage is capped so the bar never distorts wildly
  // when far over. Both fractions are taken over the same (possibly > target)
  // total so they share the track proportionally.
  const cappedOver = isOver ? Math.min(consumed - target, target * 0.35) : 0;
  const total = target + cappedOver;
  if (total <= 0) return { amber: 0, coral: 0 };
  return {
    amber: Math.min(consumed, target) / total,
    coral: cappedOver / total,
  };
}

function ProgressBar({
  consumed,
  target,
  isOver,
  amberColor,
  coralColor,
  trackColor,
  reduceMotion,
}: {
  consumed: number;
  target: number;
  isOver: boolean;
  amberColor: string;
  coralColor: string;
  trackColor: string;
  reduceMotion: boolean;
}) {
  const { amber, coral } = barFractions(consumed, target, isOver);

  // Animated fill fractions. Seeded to the current value so the bar shows the
  // right proportion on first paint (no animate-from-empty on mount); subsequent
  // value changes ease with the shared `defaultSpring`. Width is a layout prop,
  // so the animation runs on the JS driver (native driver can't drive layout).
  // Held in state (lazy initializer) so each Animated.Value is created once.
  const [amberFill] = useState(() => new Animated.Value(amber));
  const [coralFill] = useState(() => new Animated.Value(coral));

  useEffect(() => {
    if (reduceMotion) {
      // Reduce Motion: set the value directly, no spring.
      amberFill.setValue(amber);
      coralFill.setValue(coral);
      return;
    }
    Animated.spring(amberFill, {
      ...defaultSpring,
      toValue: amber,
      useNativeDriver: false,
    }).start();
    Animated.spring(coralFill, {
      ...defaultSpring,
      toValue: coral,
      useNativeDriver: false,
    }).start();
  }, [amber, coral, reduceMotion, amberFill, coralFill]);

  const amberWidth = amberFill.interpolate({
    inputRange: [0, 1],
    outputRange: ["0%", "100%"],
    extrapolate: "clamp",
  });
  const coralWidth = coralFill.interpolate({
    inputRange: [0, 1],
    outputRange: ["0%", "100%"],
    extrapolate: "clamp",
  });

  return (
    <View
      style={[styles.barTrack, { backgroundColor: trackColor }]}
      accessibilityElementsHidden
    >
      <Animated.View
        style={[styles.barFill, { width: amberWidth, backgroundColor: amberColor }]}
        testID="calorie-hero-bar-fill"
      />
      {isOver ? (
        <Animated.View
          style={[styles.barFill, { width: coralWidth, backgroundColor: coralColor }]}
          testID="calorie-hero-bar-overfill"
        />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    borderRadius: radius.lg,
    paddingVertical: spacing.lg,
    paddingHorizontal: spacing.base,
    marginBottom: spacing.sm,
    gap: spacing.xs,
  },
  heroNumber: {
    lineHeight: typeScale.heroDisplay * 1.05,
  },
  contextLine: {
    fontSize: typeScale.callout,
    fontWeight: "500",
    fontVariant: ["tabular-nums"],
  },
  subLine: {
    fontSize: typeScale.subhead,
    marginTop: spacing.xs,
  },
  barTrack: {
    height: 6,
    borderRadius: radius.full,
    flexDirection: "row",
    overflow: "hidden",
    marginTop: spacing.xs,
  },
  barFill: {
    height: 6,
  },
});
