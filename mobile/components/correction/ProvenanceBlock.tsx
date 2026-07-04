/**
 * FTY-204: Provenance / evidence block for the correction sheet.
 *
 * Shows the item's source line (or "≈ Rough estimate"), a "Make it exact" nudge
 * for rough estimates, and the user's original quoted phrase. Extracted from the
 * former monolithic `CorrectionSheet.tsx` — behaviour, copy, and accessibility
 * labels are unchanged.
 */

import { Pressable, StyleSheet, Text, View } from "react-native";

import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import { AppIcon } from "@/components/ui/AppIcon";
import type { ProvenancePresentation } from "@/components/ui/ProvenanceIcon";
import { spacing, typeScale, type ColorPalette } from "@/theme";

export function ProvenanceBlock({
  source,
  isEdited,
  provenancePres,
  isRoughEstimate,
  logPhrase,
  onMakeExact,
  colors,
}: {
  source: DerivedFoodItemDTO["source"];
  isEdited: boolean;
  provenancePres: ProvenancePresentation;
  isRoughEstimate: boolean;
  logPhrase?: string;
  onMakeExact: () => void;
  colors: ColorPalette;
}) {
  const sourceLabel = isEdited
    ? "You edited"
    : source?.label ?? "Unknown source";

  return (
    <View style={styles.provenanceBlock} accessibilityRole="summary">
      {/* Source line */}
      <View style={styles.provenanceRow}>
        <View style={styles.provenanceGlyph}>
          <AppIcon
            name={provenancePres.icon}
            size={16}
            color={colors.textMuted}
            accessibilityLabel={provenancePres.accessibilityLabel}
          />
        </View>
        <Text style={[styles.provenanceLabel, { color: colors.textSecondary }]}>
          {isRoughEstimate ? "≈ Rough estimate" : sourceLabel}
        </Text>
      </View>

      {/* Rough estimate nudge */}
      {isRoughEstimate ? (
        <Pressable
          onPress={onMakeExact}
          style={styles.makeExactRow}
          accessibilityRole="button"
          accessibilityLabel="Make it exact — find the real source"
        >
          <Text style={[styles.makeExactLabel, { color: colors.accentText }]}>
            › Make it exact
          </Text>
        </Pressable>
      ) : null}

      {/* Original phrase */}
      {logPhrase ? (
        <Text style={[styles.originalPhrase, { color: colors.textMuted }]}>
          {`"${logPhrase}"`}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  provenanceBlock: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    gap: spacing.xs,
  },
  provenanceRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  provenanceGlyph: {
    width: 22,
    alignItems: "center",
  },
  provenanceLabel: {
    fontSize: typeScale.subhead,
    flex: 1,
  },
  makeExactRow: {
    paddingVertical: spacing.xs,
    paddingLeft: 30,
    minHeight: 44,
    justifyContent: "center",
  },
  makeExactLabel: {
    fontSize: typeScale.subhead,
    fontWeight: "500",
  },
  originalPhrase: {
    fontSize: typeScale.footnote,
    paddingLeft: 30,
    fontStyle: "italic",
  },
});
