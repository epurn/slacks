import { StyleSheet, Text, View } from "react-native";

import type { TargetReadModel } from "@/api/dailySummary";
import { AppIcon } from "@/components/ui/AppIcon";
import { useTheme, spacing, typeScale, radius } from "@/theme";

type MacroKey = "protein_g" | "carbs_g" | "fat_g";

const MACROS: readonly { key: MacroKey; short: string; name: string }[] = [
  { key: "protein_g", short: "P", name: "Protein" },
  { key: "carbs_g", short: "C", name: "Carbs" },
  { key: "fat_g", short: "F", name: "Fat" },
];

/**
 * Secondary tier below the CalorieHero (spec §4): compact macro chips measured
 * against their targets ("P 80/128g") and a visually distinct exercise burn
 * line.
 *
 * Two separations the design requires:
 *  - Macros are chips, not oversized cards; each reads consumed-vs-target from
 *    the daily-summary target read-model (`target.{protein,carbs,fat}_g.effective`,
 *    FTY-094/095). When no target is set (`target` is `null`) the chips fall back
 *    to consumed-grams only — never a fabricated denominator.
 *  - Exercise burn is its own row, never a fourth macro chip and never folded into
 *    the hero's food/calorie math. Its glyph comes from the icon system (SF Symbol
 *    flame via expo-symbols) — no emoji as UI chrome. The row hides calmly at 0.
 */
export function MacroTier({
  protein_g,
  carbs_g,
  fat_g,
  target,
  active_calories,
}: {
  protein_g: number;
  carbs_g: number;
  fat_g: number;
  target: TargetReadModel | null;
  active_calories: number;
}) {
  const { colors } = useTheme();
  const consumed: Record<MacroKey, number> = {
    protein_g,
    carbs_g,
    fat_g,
  };

  return (
    <View style={styles.container}>
      {/* Macro chips — consumed vs. target from the target read-model, or
          consumed-only when no target is set. */}
      <View style={styles.chips}>
        {MACROS.map(({ key, short, name }) => (
          <MacroChip
            key={key}
            short={short}
            name={name}
            consumed={consumed[key]}
            targetG={target ? target[key].effective : null}
            colors={colors}
          />
        ))}
      </View>

      {/* Exercise burn — distinct row, icon system glyph, never a macro chip and
          never netted into the food/calorie math. Hidden calmly when 0. */}
      {active_calories > 0 ? (
        <View
          style={styles.burnLine}
          accessible={true}
          accessibilityLabel={`Burned: ${Math.round(active_calories)} kcal`}
        >
          <AppIcon name="flame.fill" size={14} color={colors.textSecondary} />
          <Text style={[styles.burnText, { color: colors.textSecondary }]}>
            {`${Math.round(active_calories)} kcal burned`}
          </Text>
        </View>
      ) : null}
    </View>
  );
}

function MacroChip({
  short,
  name,
  consumed,
  targetG,
  colors,
}: {
  short: string;
  name: string;
  consumed: number;
  targetG: number | null;
  colors: {
    readonly surfaceRaised: string;
    readonly text: string;
    readonly textMuted: string;
  };
}) {
  const consumedG = Math.round(consumed);
  const value = targetG !== null ? `${consumedG}/${targetG}g` : `${consumedG}g`;
  const a11yLabel =
    targetG !== null
      ? `${name} ${consumedG} of ${targetG} grams`
      : `${name} ${consumedG} grams`;

  return (
    <View
      style={[styles.chip, { backgroundColor: colors.surfaceRaised }]}
      accessibilityLabel={a11yLabel}
      accessible={true}
    >
      <Text style={[styles.chipLabel, { color: colors.textMuted }]}>
        {short}
      </Text>
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
    flexDirection: "row",
    alignItems: "baseline",
    justifyContent: "center",
    borderRadius: radius.md,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.sm,
    gap: spacing.xs,
  },
  chipLabel: {
    fontSize: typeScale.footnote,
    fontWeight: "600",
    textTransform: "uppercase",
  },
  chipValue: {
    fontSize: typeScale.subhead,
    fontWeight: "600",
    fontVariant: ["tabular-nums"],
  },
  burnLine: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    paddingHorizontal: spacing.xs,
  },
  burnText: {
    fontSize: typeScale.subhead,
  },
});
