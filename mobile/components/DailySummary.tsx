import { StyleSheet, Text, View } from "react-native";

import type { DailySummaryDTO } from "@/api/dailySummary";

/**
 * Daily summary header for the Today screen (FTY-075): shows the day's intake
 * (calories and macros), target, and exercise burn as separate, distinct figures
 * per the contract and roadmap acceptance. Net (intake − burn) is not shown to
 * avoid conflating the components. The summary is backed by the daily-summary
 * endpoint (FTY-071) and updates as entries reach terminal status via the
 * existing refresh mechanism (FTY-032).
 *
 * Renders gracefully on error or with empty-day zeroed totals. Returns null
 * when summary is null and there is no error.
 * Accessible labels are paired with each figure for screen-reader users.
 */
export function DailySummary({
  summary,
  error = null,
}: {
  summary?: DailySummaryDTO | null;
  error?: string | null;
} = {}) {
  if (error) {
    return (
      <View style={styles.container}>
        <Text style={styles.errorText} accessibilityRole="alert">
          {error}
        </Text>
      </View>
    );
  }

  if (!summary) {
    return null;
  }

  return (
    <View
      style={styles.container}
      accessible={true}
      accessibilityRole="header"
    >
      <View style={styles.grid}>
        <View style={styles.stat}>
          <Text style={styles.label}>Intake</Text>
          <Text
            style={styles.value}
            accessibilityLabel={`Intake: ${Math.round(summary.intake.calories)} calories`}
          >
            {Math.round(summary.intake.calories)}
          </Text>
          <Text style={styles.unit}>kcal</Text>
        </View>

        <View style={styles.stat}>
          <Text style={styles.label}>Protein</Text>
          <Text
            style={styles.value}
            accessibilityLabel={`Protein: ${Math.round(summary.intake.protein_g)} grams`}
          >
            {Math.round(summary.intake.protein_g)}
          </Text>
          <Text style={styles.unit}>g</Text>
        </View>

        <View style={styles.stat}>
          <Text style={styles.label}>Carbs</Text>
          <Text
            style={styles.value}
            accessibilityLabel={`Carbs: ${Math.round(summary.intake.carbs_g)} grams`}
          >
            {Math.round(summary.intake.carbs_g)}
          </Text>
          <Text style={styles.unit}>g</Text>
        </View>

        <View style={styles.stat}>
          <Text style={styles.label}>Fat</Text>
          <Text
            style={styles.value}
            accessibilityLabel={`Fat: ${Math.round(summary.intake.fat_g)} grams`}
          >
            {Math.round(summary.intake.fat_g)}
          </Text>
          <Text style={styles.unit}>g</Text>
        </View>

        {summary.target ? (
          <View style={styles.stat}>
            <Text style={styles.label}>Target</Text>
            <Text
              style={styles.value}
              accessibilityLabel={`Target: ${summary.target.calories} calories`}
            >
              {summary.target.calories}
            </Text>
            <Text style={styles.unit}>kcal</Text>
          </View>
        ) : null}

        <View style={styles.stat}>
          <Text style={styles.label}>Exercise</Text>
          <Text
            style={styles.value}
            accessibilityLabel={`Exercise burn: ${Math.round(summary.exercise.active_calories)} calories`}
          >
            {Math.round(summary.exercise.active_calories)}
          </Text>
          <Text style={styles.unit}>kcal</Text>
        </View>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: "#FFFFFF",
    borderRadius: 12,
    marginBottom: 16,
    paddingVertical: 16,
    paddingHorizontal: 12,
    justifyContent: "center",
    alignItems: "center",
  },
  grid: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
  },
  stat: {
    flex: 1,
    minWidth: "48%",
    alignItems: "center",
    justifyContent: "center",
    paddingVertical: 8,
    paddingHorizontal: 4,
  },
  label: {
    fontSize: 12,
    color: "#8E8E93",
    marginBottom: 4,
    fontWeight: "500",
  },
  value: {
    fontSize: 18,
    fontWeight: "600",
    color: "#1C1C1E",
  },
  unit: {
    fontSize: 11,
    color: "#8E8E93",
    marginTop: 2,
  },
  errorText: {
    fontSize: 13,
    color: "#C0392B",
    textAlign: "center",
  },
});
