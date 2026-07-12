/**
 * FTY-312: exact-evidence proposal preview.
 *
 * Shows what an exact-evidence proposal would do to the item **before** anything
 * changes: the proposed source (with its always-on provenance icon), whether the
 * result is `exact` or an honestly-rough `fallback`, the current vs proposed
 * nutrition, and an amount control. The user confirms with Apply, or takes one of
 * the always-available paths back — Try again, Change match, Manual edit, Cancel.
 *
 * A fallback is never labelled exact: it carries the fallback notice and a
 * lower-trust "≈ Rough fallback" source line, matching the provenance principle.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import { DisplayText } from "@/components/ui/DisplayText";
import { AppIcon } from "@/components/ui/AppIcon";
import { provenancePresentation } from "@/components/ui/ProvenanceIcon";
import { radius, spacing, typeScale, type ColorPalette } from "@/theme";

import { formatAmount } from "./helpers";
import { fallbackNotice, type ApplyableProposal } from "./useExactEvidence";

function macroLine(
  calories: number | null,
  protein: number | null,
  carbs: number | null,
  fat: number | null,
): string {
  const kcal = calories !== null ? `${Math.round(calories)} kcal` : "—";
  return `${kcal} · P ${formatAmount(protein)}g · C ${formatAmount(carbs)}g · F ${formatAmount(fat)}g`;
}

export function ExactProposalPreview({
  item,
  proposal,
  amount,
  needsAmount,
  onStepAmount,
  applying,
  error,
  onApply,
  onTryAgain,
  onChangeMatch,
  onManualEdit,
  onCancel,
  colors,
}: {
  item: DerivedFoodItemDTO;
  proposal: ApplyableProposal;
  amount: number;
  /**
   * This proposal can't cost the item's current amount, so Apply stays blocked
   * until the user sets an explicit amount — the client never guesses a portion.
   */
  needsAmount: boolean;
  onStepAmount: (delta: number) => void;
  applying: boolean;
  error: string | null;
  onApply: () => void;
  onTryAgain: () => void;
  onChangeMatch: () => void;
  onManualEdit: () => void;
  onCancel: () => void;
  colors: ColorPalette;
}) {
  const { preview } = proposal;
  const isExact = proposal.quality === "exact";
  const pres = provenancePresentation(preview.source, false);
  const unit = item.unit ? ` ${item.unit}` : "";

  return (
    <View style={styles.panel}>
      <View style={styles.header}>
        <DisplayText scale="headline" style={styles.title}>
          Make it exact
        </DisplayText>
        <Pressable
          onPress={onCancel}
          accessibilityLabel="Cancel make it exact"
          accessibilityRole="button"
          style={styles.headerButton}
        >
          <Text style={[styles.headerButtonLabel, { color: colors.accentText }]}>
            Cancel
          </Text>
        </Pressable>
      </View>

      {/* Exact vs fallback state — the trust signal, never mislabelled. */}
      {isExact ? (
        <View
          style={styles.stateRow}
          accessibilityLabel={`Exact match from ${preview.source.label}`}
        >
          <AppIcon
            name={pres.icon}
            size={16}
            color={colors.textMuted}
            accessibilityLabel={pres.accessibilityLabel}
          />
          <Text style={[styles.exactLabel, { color: colors.text }]}>
            {`Exact match · ${preview.source.label}`}
          </Text>
        </View>
      ) : (
        <View
          style={[styles.fallbackBox, { backgroundColor: colors.controlBackground }]}
          accessibilityLabel="Rough fallback — exact evidence wasn't found"
        >
          <Text style={[styles.fallbackNotice, { color: colors.text }]}>
            {fallbackNotice(proposal.kind)}
          </Text>
          <View style={styles.stateRow}>
            <AppIcon
              name={pres.icon}
              size={16}
              color={colors.textMuted}
              accessibilityLabel={pres.accessibilityLabel}
            />
            <Text style={[styles.fallbackSource, { color: colors.textSecondary }]}>
              {`≈ Rough fallback · ${preview.source.label}`}
            </Text>
          </View>
        </View>
      )}

      {/* Now → After nutrition comparison (server-projected values, no client math). */}
      <View style={styles.compareBlock}>
        <View style={styles.compareRow}>
          <Text style={[styles.compareLabel, { color: colors.textSecondary }]}>Now</Text>
          <Text
            style={[styles.compareValue, { color: colors.textMuted }]}
            accessibilityLabel={`Current: ${macroLine(item.calories, item.protein_g, item.carbs_g, item.fat_g)}`}
          >
            {macroLine(item.calories, item.protein_g, item.carbs_g, item.fat_g)}
          </Text>
        </View>
        <View style={styles.compareRow}>
          <Text style={[styles.compareLabel, { color: colors.textSecondary }]}>After</Text>
          <Text
            style={[styles.compareValue, { color: colors.text }]}
            accessibilityLabel={`Proposed: ${macroLine(preview.calories, preview.protein_g, preview.carbs_g, preview.fat_g)}`}
          >
            {macroLine(preview.calories, preview.protein_g, preview.carbs_g, preview.fat_g)}
          </Text>
        </View>
      </View>

      {/* Amount — adjustable before Apply; sent as amount only. */}
      <View style={styles.amountRow}>
        <Text style={[styles.sectionLabel, { color: colors.textSecondary }]}>
          Amount
        </Text>
        <View style={styles.stepper}>
          <Pressable
            onPress={() => onStepAmount(-0.25)}
            style={[styles.stepperButton, { backgroundColor: colors.controlBackground }]}
            accessibilityLabel="Decrease amount"
            accessibilityRole="button"
            disabled={applying || amount <= 0.25}
            accessibilityState={{ disabled: applying || amount <= 0.25 }}
          >
            <Text style={[styles.stepperButtonLabel, { color: colors.text }]}>−</Text>
          </Pressable>
          <DisplayText
            scale="title3"
            tabularNums
            style={styles.amountValue}
            accessibilityLabel={`Amount: ${formatAmount(amount)}${unit}`}
          >
            {`${formatAmount(amount)}${unit}`}
          </DisplayText>
          <Pressable
            onPress={() => onStepAmount(0.25)}
            style={[styles.stepperButton, { backgroundColor: colors.controlBackground }]}
            accessibilityLabel="Increase amount"
            accessibilityRole="button"
            disabled={applying}
            accessibilityState={{ disabled: applying }}
          >
            <Text style={[styles.stepperButtonLabel, { color: colors.text }]}>+</Text>
          </Pressable>
        </View>
        {preview.serving_label ? (
          <Text style={[styles.servingLabel, { color: colors.textMuted }]}>
            {preview.serving_label}
          </Text>
        ) : null}
        {needsAmount ? (
          <Text
            style={[styles.amountHint, { color: colors.textSecondary }]}
            accessibilityLabel="Set an amount to apply this source"
          >
            Set an amount to apply this — the current portion cannot be costed.
          </Text>
        ) : null}
      </View>

      {error ? (
        <Text style={[styles.errorText, { color: colors.coral }]} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}

      {/* Primary action */}
      <Pressable
        onPress={onApply}
        style={[
          styles.applyButton,
          { backgroundColor: colors.accent },
          (applying || needsAmount) && styles.applyButtonDisabled,
        ]}
        accessibilityLabel="Apply"
        accessibilityHint={
          needsAmount
            ? "Set an amount first to apply this source"
            : "Applies this source to the item"
        }
        accessibilityRole="button"
        disabled={applying || needsAmount}
        accessibilityState={{ disabled: applying || needsAmount }}
      >
        <Text style={[styles.applyLabel, { color: colors.accentForeground }]}>
          {applying ? "Applying…" : "Apply"}
        </Text>
      </Pressable>

      {/* Secondary paths — always a way back. */}
      <View style={styles.secondaryRow}>
        <SecondaryAction label="Try again" onPress={onTryAgain} disabled={applying} colors={colors} />
        <SecondaryAction label="Change match" onPress={onChangeMatch} disabled={applying} colors={colors} />
        <SecondaryAction label="Manual edit" onPress={onManualEdit} disabled={applying} colors={colors} />
      </View>
    </View>
  );
}

function SecondaryAction({
  label,
  onPress,
  disabled,
  colors,
}: {
  label: string;
  onPress: () => void;
  disabled: boolean;
  colors: ColorPalette;
}) {
  return (
    <Pressable
      onPress={onPress}
      accessibilityLabel={label}
      accessibilityRole="button"
      style={styles.secondaryButton}
      disabled={disabled}
      accessibilityState={{ disabled }}
    >
      <Text style={[styles.secondaryLabel, { color: colors.accentText }]}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  panel: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    gap: spacing.md,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
  },
  title: {
    flex: 1,
  },
  headerButton: {
    minHeight: 44,
    minWidth: 44,
    alignItems: "flex-end",
    justifyContent: "center",
  },
  headerButtonLabel: {
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  stateRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  exactLabel: {
    fontSize: typeScale.callout,
    fontWeight: "600",
    flex: 1,
  },
  fallbackBox: {
    borderRadius: radius.md,
    padding: spacing.md,
    gap: spacing.sm,
  },
  fallbackNotice: {
    fontSize: typeScale.subhead,
  },
  fallbackSource: {
    fontSize: typeScale.footnote,
    flex: 1,
  },
  compareBlock: {
    gap: spacing.xs,
  },
  compareRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  compareLabel: {
    fontSize: typeScale.footnote,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.5,
    width: 56,
  },
  compareValue: {
    fontSize: typeScale.footnote,
    fontVariant: ["tabular-nums"],
    flex: 1,
  },
  amountRow: {
    gap: spacing.sm,
  },
  sectionLabel: {
    fontSize: typeScale.footnote,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  stepper: {
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
    fontSize: typeScale.title2,
    fontWeight: "300",
  },
  amountValue: {
    flex: 1,
    textAlign: "center",
  },
  servingLabel: {
    fontSize: typeScale.footnote,
  },
  amountHint: {
    fontSize: typeScale.footnote,
  },
  errorText: {
    fontSize: typeScale.footnote,
  },
  applyButton: {
    minHeight: 48,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  applyButtonDisabled: {
    opacity: 0.5,
  },
  applyLabel: {
    fontSize: typeScale.callout,
    fontWeight: "700",
  },
  secondaryRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  secondaryButton: {
    minHeight: 44,
    justifyContent: "center",
    paddingHorizontal: spacing.xs,
  },
  secondaryLabel: {
    fontSize: typeScale.subhead,
    fontWeight: "500",
  },
});
