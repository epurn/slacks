/**
 * FTY-204: Advanced override panel — direct field edit that marks the item
 * user-edited (FTY-051). Extracted from the former monolithic
 * `CorrectionSheet.tsx` — behaviour, copy, and accessibility labels unchanged.
 */

import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { radius, spacing, typeScale, type ColorPalette } from "@/theme";

const FIELD_LABELS: Record<string, { label: string; unit: string }> = {
  calories: { label: "Calories", unit: "kcal" },
  protein_g: { label: "Protein", unit: "g" },
  carbs_g: { label: "Carbs", unit: "g" },
  fat_g: { label: "Fat", unit: "g" },
};

export function OverridePanel({
  field,
  draft,
  saving,
  error,
  onChangeDraft,
  onSubmit,
  onCancel,
  colors,
}: {
  field: string;
  draft: string;
  saving: boolean;
  error: string | null;
  onChangeDraft: (v: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  colors: ColorPalette;
}) {
  const meta = FIELD_LABELS[field] ?? { label: field, unit: "" };

  return (
    <View style={styles.overridePanel}>
      <View style={styles.overridePanelHeader}>
        <Text style={[styles.overridePanelTitle, { color: colors.text }]}>
          Override {meta.label}
        </Text>
        <Text style={[styles.overridePanelNote, { color: colors.textMuted }]}>
          Marks this entry {'"'}✎ edited{'"'}
        </Text>
      </View>

      <View style={styles.overrideInputRow}>
        <TextInput
          accessibilityLabel={`${meta.label} value`}
          value={draft}
          onChangeText={onChangeDraft}
          keyboardType="decimal-pad"
          inputMode="decimal"
          autoFocus
          editable={!saving}
          style={[
            styles.overrideInput,
            {
              backgroundColor: colors.surfaceRaised,
              color: colors.text,
              borderColor: colors.separator,
            },
          ]}
          selectTextOnFocus
        />
        {meta.unit ? (
          <Text style={[styles.overrideUnit, { color: colors.textMuted }]}>
            {meta.unit}
          </Text>
        ) : null}
      </View>

      {error ? (
        <Text style={[styles.errorText, { color: colors.coral }]} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}

      <View style={styles.overrideActions}>
        <Pressable
          onPress={onCancel}
          style={[styles.overrideCancelBtn, { backgroundColor: colors.controlBackground }]}
          accessibilityRole="button"
          accessibilityLabel="Cancel override"
          disabled={saving}
        >
          <Text style={[styles.overrideCancelLabel, { color: colors.textSecondary }]}>
            Cancel
          </Text>
        </Pressable>
        <Pressable
          onPress={onSubmit}
          style={[styles.overrideSaveBtn, { backgroundColor: colors.accent }]}
          accessibilityRole="button"
          accessibilityLabel={`Save ${meta.label} override`}
          disabled={saving}
          accessibilityState={{ disabled: saving }}
        >
          <Text style={[styles.overrideSaveLabel, { color: colors.accentForeground }]}>
            {saving ? "Saving…" : "Save"}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  overridePanel: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    gap: spacing.md,
  },
  overridePanelHeader: {
    gap: spacing.xs,
  },
  overridePanelTitle: {
    fontSize: typeScale.headline,
    fontWeight: "600",
  },
  overridePanelNote: {
    fontSize: typeScale.footnote,
  },
  overrideInputRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  overrideInput: {
    flex: 1,
    height: 48,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: spacing.md,
    fontSize: typeScale.callout,
    textAlign: "right",
  },
  overrideUnit: {
    fontSize: typeScale.subhead,
    minWidth: 36,
  },
  overrideActions: {
    flexDirection: "row",
    gap: spacing.sm,
  },
  overrideCancelBtn: {
    flex: 1,
    height: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  overrideCancelLabel: {
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  overrideSaveBtn: {
    flex: 1,
    height: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  overrideSaveLabel: {
    fontSize: typeScale.callout,
    fontWeight: "600",
  },
  errorText: {
    fontSize: typeScale.footnote,
  },
});
