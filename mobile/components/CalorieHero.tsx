import { StyleSheet, Text, View } from "react-native";

import {
  useTheme,
  DISPLAY_FONT_FAMILY,
  spacing,
  radius,
  typeScale,
} from "@/theme";

function formatCalories(n: number): string {
  return Math.round(n).toLocaleString("en-US");
}

function pct(consumed: number, target: number): number {
  if (target <= 0) return 0;
  return Math.round((consumed / target) * 100);
}

/**
 * The Today hero: calories consumed vs. target, with a slim progress bar.
 *
 * States:
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
}: {
  consumed: number;
  target: number | null;
}) {
  const { colors } = useTheme();

  if (target === null) {
    return (
      <View
        style={[styles.container, { backgroundColor: colors.surfaceRaised }]}
        accessible={true}
        accessibilityLabel={`${formatCalories(consumed)} kcal today, no target set`}
      >
        <Text
          style={[
            styles.heroNumber,
            { color: colors.text, fontFamily: DISPLAY_FONT_FAMILY },
          ]}
          accessibilityElementsHidden
        >
          {formatCalories(consumed)}
        </Text>
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

  // A11y: combine all hero data into one clear sentence.
  const a11yLabel = isOver
    ? `${formatCalories(consumed)} of ${formatCalories(target)} kcal, ${formatCalories(over)} over budget`
    : `${formatCalories(consumed)} of ${formatCalories(target)} kcal, ${percentage} percent, ${formatCalories(remaining)} remaining`;

  return (
    <View
      style={[styles.container, { backgroundColor: colors.surfaceRaised }]}
      accessible={true}
      accessibilityLabel={a11yLabel}
    >
      <Text
        style={[
          styles.heroNumber,
          { color: colors.text, fontFamily: DISPLAY_FONT_FAMILY },
        ]}
        accessibilityElementsHidden
      >
        {formatCalories(consumed)}
      </Text>

      <Text
        style={[styles.contextLine, { color: colors.textSecondary }]}
        accessibilityElementsHidden
      >
        {`/ of ${formatCalories(target)} kcal · ${percentage}%`}
      </Text>

      {/* Slim progress bar */}
      <ProgressBar
        consumed={consumed}
        target={target}
        isOver={isOver}
        amberColor={colors.accent}
        coralColor={colors.coral}
        trackColor={colors.separator}
      />

      {/* "X to go" / "X over" copy — always text, never color alone */}
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
    </View>
  );
}

function ProgressBar({
  consumed,
  target,
  isOver,
  amberColor,
  coralColor,
  trackColor,
}: {
  consumed: number;
  target: number;
  isOver: boolean;
  amberColor: string;
  coralColor: string;
  trackColor: string;
}) {
  // For over-budget: amber flex = target, coral flex = capped overage.
  // The capped coral prevents extreme visual distortion when far over.
  const cappedOver = isOver
    ? Math.min(consumed - target, target * 0.35)
    : 0;

  return (
    <View
      style={[styles.barTrack, { backgroundColor: trackColor }]}
      accessibilityElementsHidden
    >
      {isOver ? (
        <>
          <View
            style={[
              styles.barFill,
              { flex: target, backgroundColor: amberColor },
            ]}
          />
          <View
            style={[
              styles.barFill,
              { flex: cappedOver, backgroundColor: coralColor },
            ]}
          />
        </>
      ) : (
        <>
          <View
            style={[
              styles.barFill,
              { flex: consumed, backgroundColor: amberColor },
            ]}
          />
          <View
            style={[styles.barFill, { flex: Math.max(target - consumed, 0) }]}
          />
        </>
      )}
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
    fontSize: typeScale.heroDisplay,
    fontWeight: "700",
    fontVariant: ["tabular-nums"],
    letterSpacing: -1,
    lineHeight: typeScale.heroDisplay * 1.05,
  },
  contextLine: {
    fontSize: typeScale.callout,
    fontWeight: "500",
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
