import { StyleSheet, Text, View } from "react-native";

import type { DailySummaryDTO } from "@/api/dailySummary";
import { CalorieHero } from "@/components/CalorieHero";
import { MacroTier } from "@/components/MacroTier";
import { useTheme, spacing, typeScale } from "@/theme";

/**
 * Today screen status-first header (FTY-098 redesign).
 *
 * Replaced the old 4-tile grid (FTY-075) with:
 *   1. CalorieHero — bold display number + slim progress bar (consumed vs. target)
 *   2. MacroTier — P/C/F chips (consumed grams) + distinct exercise burn line
 *
 * Returns null when no summary and no error (same contract as before).
 * Renders gracefully on error or with empty-day zeroed totals.
 */
export function DailySummary({
  summary,
  error = null,
}: {
  summary?: DailySummaryDTO | null;
  error?: string | null;
} = {}) {
  const { colors } = useTheme();

  if (error) {
    return (
      <View style={styles.errorContainer}>
        <Text
          style={[styles.errorText, { color: colors.coral }]}
          accessibilityRole="alert"
        >
          {error}
        </Text>
      </View>
    );
  }

  if (!summary) {
    return null;
  }

  return (
    <View style={styles.wrapper}>
      <CalorieHero
        consumed={summary.intake.calories}
        target={summary.target?.calories.effective ?? null}
      />
      <MacroTier
        protein_g={summary.intake.protein_g}
        carbs_g={summary.intake.carbs_g}
        fat_g={summary.intake.fat_g}
        active_calories={summary.exercise.active_calories}
      />
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
  },
  errorText: {
    fontSize: typeScale.footnote,
    textAlign: "center",
  },
});
