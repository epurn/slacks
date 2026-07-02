import { Pressable, StyleSheet, Text, View } from "react-native";

import type { DailySummaryDTO } from "@/api/dailySummary";
import { CalorieHero } from "@/components/CalorieHero";
import { MacroTier } from "@/components/MacroTier";
import { useTheme, spacing, typeScale, radius } from "@/theme";

/**
 * Today screen status-first header (FTY-098 redesign).
 *
 * Replaced the old 4-tile grid (FTY-075) with:
 *   1. CalorieHero — bold display number + slim progress bar (consumed vs. target)
 *   2. MacroTier — P/C/F chips (consumed grams) + distinct exercise burn line
 *
 * Always renders the hero shell, including while the summary is missing or the
 * summary read failed, so Today never blanks out its status anchor.
 */
export function DailySummary({
  summary,
  error = null,
  onRetry,
  showMacros = true,
}: {
  summary?: DailySummaryDTO | null;
  error?: string | null;
  onRetry?: () => void;
  /**
   * Today mounts the hero alone above the composer (FTY-178) and keeps the
   * macro tier in its pre-existing spot below it until FTY-179 reworks that
   * tier; the historical day view keeps the combined default.
   */
  showMacros?: boolean;
} = {}) {
  const { colors } = useTheme();
  const summaryState = summary ? "ready" : error ? "unavailable" : "loading";

  return (
    <View style={styles.wrapper}>
      <CalorieHero
        consumed={summary?.intake.calories ?? 0}
        target={summary?.target?.calories.effective ?? null}
        hasIntake={summary?.has_intake ?? false}
        summaryState={summaryState}
      />
      {showMacros && summary ? (
        <MacroTier
          protein_g={summary.intake.protein_g}
          carbs_g={summary.intake.carbs_g}
          fat_g={summary.intake.fat_g}
          active_calories={summary.exercise.active_calories}
        />
      ) : null}
      {error ? (
        <View style={styles.errorContainer}>
          <Text
            style={[styles.errorText, { color: colors.textSecondary }]}
            accessibilityRole="alert"
          >
            {error}
          </Text>
          {onRetry ? (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Retry summary"
              onPress={onRetry}
              style={[
                styles.retry,
                { backgroundColor: colors.controlBackground },
              ]}
            >
              <Text style={[styles.retryLabel, { color: colors.text }]}>
                Try again
              </Text>
            </Pressable>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrapper: {
    gap: spacing.xs,
    marginBottom: spacing.sm,
  },
  errorContainer: {
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.base,
    alignItems: "center",
    gap: spacing.sm,
  },
  errorText: {
    fontSize: typeScale.footnote,
    textAlign: "center",
  },
  retry: {
    paddingVertical: 8,
    paddingHorizontal: 16,
    borderRadius: radius.md,
    minHeight: 44,
    justifyContent: "center",
  },
  retryLabel: {
    fontSize: typeScale.subhead,
    fontWeight: "600",
  },
});
