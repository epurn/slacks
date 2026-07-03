/**
 * FTY-204: Amount stepper — the primary, provenance-preserving portion lever.
 *
 * Renders the ± portion controls and the server-returned nutrition row (never
 * client math). Extracted from the former monolithic `CorrectionSheet.tsx` —
 * behaviour, copy, and accessibility labels are unchanged.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import { Skeleton } from "@/components/ui/Skeleton";
import { radius, spacing, typeScale, type ColorPalette } from "@/theme";

import { formatAmount } from "./helpers";

export function AmountStepper({
  amount,
  unit,
  quantityText,
  kcal,
  protein,
  carbs,
  fat,
  pending,
  error,
  onStepDown,
  onStepUp,
  colors,
}: {
  amount: number | null;
  unit: string | null;
  quantityText: string;
  kcal: number | null;
  protein: number | null;
  carbs: number | null;
  fat: number | null;
  pending: boolean;
  error: string | null;
  onStepDown: () => void;
  onStepUp: () => void;
  colors: ColorPalette;
}) {
  const amountDisplay = amount !== null
    ? `${formatAmount(amount)}${unit ? ` ${unit}` : ""}`
    : quantityText;

  return (
    <View style={styles.stepperSection}>
      <Text style={[styles.sectionLabel, { color: colors.textSecondary }]}>
        Portion
      </Text>
      <View style={styles.stepperRow}>
        <Pressable
          onPress={onStepDown}
          style={[styles.stepperButton, { backgroundColor: colors.controlBackground }]}
          accessibilityLabel="Decrease amount"
          accessibilityRole="button"
          disabled={pending || amount === null || amount <= 0.25}
          accessibilityState={{ disabled: pending || amount === null || amount <= 0.25 }}
        >
          <Text style={[styles.stepperButtonLabel, { color: colors.text }]}>−</Text>
        </Pressable>
        <Text style={[styles.stepperValue, { color: colors.text }]} accessibilityLabel={`Amount: ${amountDisplay}`}>
          {amountDisplay}
        </Text>
        <Pressable
          onPress={onStepUp}
          testID="today-correction-increase"
          style={[styles.stepperButton, { backgroundColor: colors.controlBackground }]}
          accessibilityLabel="Increase amount"
          accessibilityRole="button"
          disabled={pending}
          accessibilityState={{ disabled: pending }}
        >
          <Text style={[styles.stepperButtonLabel, { color: colors.text }]}>+</Text>
        </Pressable>
      </View>

      {/* Recomputed nutrition — server values only, never client math */}
      <View style={styles.nutritionRow}>
        {pending ? (
          <>
            <Skeleton width={60} height={18} borderRadius={4} />
            <Skeleton width={48} height={14} borderRadius={4} />
            <Skeleton width={48} height={14} borderRadius={4} />
            <Skeleton width={48} height={14} borderRadius={4} />
          </>
        ) : (
          <>
            <Text
              style={[styles.kcalValue, { color: colors.text }]}
              accessibilityLabel={`${kcal !== null ? Math.round(kcal) : "—"} calories`}
            >
              {kcal !== null ? `${Math.round(kcal)} kcal` : "—"}
            </Text>
            <Text style={[styles.macroChip, { color: colors.textSecondary }]} accessibilityLabel={`${formatAmount(protein)} g protein`}>
              P {formatAmount(protein)}g
            </Text>
            <Text style={[styles.macroChip, { color: colors.textSecondary }]} accessibilityLabel={`${formatAmount(carbs)} g carbs`}>
              C {formatAmount(carbs)}g
            </Text>
            <Text style={[styles.macroChip, { color: colors.textSecondary }]} accessibilityLabel={`${formatAmount(fat)} g fat`}>
              F {formatAmount(fat)}g
            </Text>
          </>
        )}
      </View>

      {error ? (
        <Text style={[styles.errorText, { color: colors.coral }]} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  stepperSection: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    gap: spacing.sm,
  },
  sectionLabel: {
    fontSize: typeScale.footnote,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  stepperRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  stepperButton: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  stepperButtonLabel: {
    fontSize: 22,
    fontWeight: "300",
  },
  stepperValue: {
    flex: 1,
    textAlign: "center",
    fontSize: typeScale.title3,
    fontWeight: "600",
    fontVariant: ["tabular-nums"],
  },
  nutritionRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    flexWrap: "wrap",
  },
  kcalValue: {
    fontSize: typeScale.callout,
    fontWeight: "700",
    fontVariant: ["tabular-nums"],
  },
  macroChip: {
    fontSize: typeScale.footnote,
    fontVariant: ["tabular-nums"],
  },
  errorText: {
    fontSize: typeScale.footnote,
  },
});
