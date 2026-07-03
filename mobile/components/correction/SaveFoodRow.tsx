/**
 * FTY-204: "Save as food" row — the manual save-as-food action (FTY-052/053).
 * Extracted from the former monolithic `CorrectionSheet.tsx` — behaviour, copy,
 * and accessibility labels unchanged.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import { radius, spacing, typeScale, type ColorPalette } from "@/theme";

export type SaveFoodStatus = "idle" | "saving" | "saved" | "error";

export function SaveFoodRow({
  status,
  error,
  onSave,
  colors,
}: {
  status: SaveFoodStatus;
  error: string | null;
  onSave: () => void;
  colors: ColorPalette;
}) {
  const disabled = status === "saving" || status === "saved";
  return (
    <View style={styles.saveFoodSection}>
      <Pressable
        onPress={onSave}
        style={[
          styles.saveFoodButton,
          { backgroundColor: status === "saved" ? colors.controlBackground : colors.controlBackground },
        ]}
        accessibilityRole="button"
        accessibilityLabel="Save as food"
        disabled={disabled}
        accessibilityState={{ disabled }}
      >
        <Text style={[styles.saveFoodLabel, { color: status === "saved" ? colors.accent : colors.textSecondary }]}>
          {status === "saving" ? "Saving…" : status === "saved" ? "Saved ✓" : "Save as food"}
        </Text>
      </Pressable>
      {status === "error" && error ? (
        <Text style={[styles.errorText, { color: colors.coral }]} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  saveFoodSection: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    gap: spacing.sm,
  },
  saveFoodButton: {
    alignSelf: "flex-start",
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: radius.md,
    minHeight: 44,
    justifyContent: "center",
  },
  saveFoodLabel: {
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  errorText: {
    fontSize: typeScale.footnote,
  },
});
