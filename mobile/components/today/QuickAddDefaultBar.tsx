import { StyleSheet, Text, View } from "react-native";

import { type FoodSuggestionDTO } from "@/api/foodSuggestions";
import { Chip } from "@/components/ui";
import { useTheme, spacing, typeScale } from "@/theme";

import { matchQuickAddDefault } from "./quickAddDefault";

/**
 * Quick-add default (FTY-408).
 *
 * As the user types a food name, this surfaces the matching prior food from
 * their own history (saved foods are already covered by the saved-food
 * typeahead — `TypeaheadSuggestionBar`) as a single accent default chip below
 * the composer. Tapping it prefills + focuses the composer via the shared
 * suggestion handler (one more tap to log, never a one-tap submit); the
 * subsequent submit re-runs the estimator, where FTY-406's prior-correction
 * tier resolves a previously-corrected food to the corrected value.
 *
 * Renders nothing — occupying no space, no empty shell — when the typed name
 * matches no prior food, so a name with no matching history leaves the composer
 * exactly as it is today.
 */
export function QuickAddDefaultBar({
  query,
  suggestions,
  onSelect,
}: {
  /** The current composer text; matched name-normalized against prior foods. */
  query: string;
  /** The user's own owner-scoped quick-add suggestions (FTY-340 pool). */
  suggestions: readonly FoodSuggestionDTO[];
  /** Prefill + focus the composer with the tapped prior food's phrase. */
  onSelect: (suggestion: FoodSuggestionDTO) => void;
}) {
  const { colors } = useTheme();
  const match = matchQuickAddDefault(query, suggestions);
  if (!match) {
    return null;
  }

  return (
    <View style={styles.bar} testID="quick-add-default">
      {/* Amber caption carries the source (provenance at a glance) and the
          brand accent; the chip keeps the legible control fill so its label
          meets AA in both light and dark. */}
      <Text style={[styles.caption, { color: colors.accentText }]}>
        From your log
      </Text>
      <Chip
        label={match.label}
        accessibilityLabel={`Quick-add from your log: ${match.label}`}
        onPress={() => onSelect(match)}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    marginTop: 6,
    // Align the caption with the composer text column (matches the typeahead).
    paddingHorizontal: spacing.base,
  },
  caption: {
    fontSize: typeScale.footnote,
  },
});
