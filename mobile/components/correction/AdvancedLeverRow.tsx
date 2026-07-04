/**
 * FTY-204: Advanced lever row — the list of directly-editable value fields that
 * opens the override panel (FTY-051). Extracted from the former monolithic
 * `CorrectionSheet.tsx` — behaviour, copy, and accessibility labels unchanged.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import { formatValue } from "@/state/derivedItems";
import { spacing, typeScale, type ColorPalette } from "@/theme";

/** Editable fields for the advanced override panel. */
const OVERRIDE_FIELDS = [
  { field: "calories", label: "Calories", unit: "kcal", key: "calories" as const },
  { field: "protein_g", label: "Protein", unit: "g", key: "protein_g" as const },
  { field: "carbs_g", label: "Carbs", unit: "g", key: "carbs_g" as const },
  { field: "fat_g", label: "Fat", unit: "g", key: "fat_g" as const },
] as const;

export function AdvancedLeverRow({
  food,
  onOpenOverride,
  colors,
}: {
  food: DerivedFoodItemDTO;
  onOpenOverride: (field: string, value: number | null) => void;
  colors: ColorPalette;
}) {
  return (
    <View style={styles.advancedSection}>
      <Text style={[styles.sectionLabel, { color: colors.textSecondary }]}>
        Advanced — edit values directly
      </Text>
      {OVERRIDE_FIELDS.map(({ field, label, unit, key }) => {
        const value = food[key];
        return (
          <Pressable
            key={field}
            onPress={() => onOpenOverride(field, value)}
            style={styles.overrideFieldRow}
            accessibilityRole="button"
            accessibilityLabel={`Override ${label}${value !== null ? `, currently ${formatValue(value)} ${unit}` : ""}`}
          >
            <Text style={[styles.overrideFieldLabel, { color: colors.textSecondary }]}>
              {label}
            </Text>
            <Text style={[styles.overrideFieldValue, { color: colors.text }]}>
              {value !== null ? `${formatValue(value)} ${unit}` : "—"}
            </Text>
            <Text style={[styles.leverChevron, { color: colors.textMuted }]}>›</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  advancedSection: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    gap: spacing.xs,
  },
  sectionLabel: {
    fontSize: typeScale.footnote,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  overrideFieldRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: spacing.md,
    minHeight: 44,
    gap: spacing.sm,
  },
  overrideFieldLabel: {
    width: 72,
    fontSize: typeScale.callout,
  },
  overrideFieldValue: {
    flex: 1,
    fontSize: typeScale.callout,
    fontVariant: ["tabular-nums"],
  },
  leverChevron: {
    fontSize: typeScale.title3,
    fontWeight: "300",
  },
});
