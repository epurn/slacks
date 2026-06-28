import { StyleSheet, Text, View } from "react-native";

import { useTheme, spacing, typeScale, radius } from "@/theme";

function roundG(g: number): string {
  return `${Math.round(g)}g`;
}

/**
 * Secondary tier below the CalorieHero: macro chips (P / C / F) and a visually
 * distinct exercise burn line. Exercise is never folded into the hero or shown as
 * a fourth macro chip — it has its own row. (FTY-098)
 */
export function MacroTier({
  protein_g,
  carbs_g,
  fat_g,
  active_calories,
}: {
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  active_calories: number;
}) {
  const { colors } = useTheme();

  return (
    <View style={styles.container}>
      {/* Macro chips — consumed grams only (targets are FTY-094) */}
      <View style={styles.chips}>
        <MacroChip label="P" value={roundG(protein_g)} colors={colors} />
        <MacroChip label="C" value={roundG(carbs_g)} colors={colors} />
        <MacroChip label="F" value={roundG(fat_g)} colors={colors} />
      </View>

      {/* Exercise burn — visually distinct row, not a chip */}
      {active_calories > 0 ? (
        <Text
          style={[styles.burnLine, { color: colors.textSecondary }]}
          accessibilityLabel={`Burned: ${Math.round(active_calories)} kcal`}
        >
          {`🔥 ${Math.round(active_calories)} kcal burned`}
        </Text>
      ) : null}
    </View>
  );
}

function MacroChip({
  label,
  value,
  colors,
}: {
  label: string;
  value: string;
  colors: { readonly surfaceRaised: string; readonly text: string; readonly textMuted: string };
}) {
  return (
    <View
      style={[styles.chip, { backgroundColor: colors.surfaceRaised }]}
      accessibilityLabel={`${label === "P" ? "Protein" : label === "C" ? "Carbs" : "Fat"}: ${value}`}
      accessible={true}
    >
      <Text style={[styles.chipLabel, { color: colors.textMuted }]}>{label}</Text>
      <Text style={[styles.chipValue, { color: colors.text }]}>{value}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    gap: spacing.sm,
    marginBottom: spacing.sm,
  },
  chips: {
    flexDirection: "row",
    gap: spacing.sm,
  },
  chip: {
    flex: 1,
    borderRadius: radius.md,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    alignItems: "center",
    gap: 2,
  },
  chipLabel: {
    fontSize: typeScale.caption1,
    fontWeight: "600",
    textTransform: "uppercase",
  },
  chipValue: {
    fontSize: typeScale.callout,
    fontWeight: "600",
    fontVariant: ["tabular-nums"],
  },
  burnLine: {
    fontSize: typeScale.subhead,
    paddingHorizontal: spacing.xs,
  },
});
