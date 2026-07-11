import { ScrollView, StyleSheet } from "react-native";

import { type FoodSuggestionDTO } from "@/api/foodSuggestions";
import { Chip } from "@/components/ui";
import { spacing } from "@/theme";

/**
 * Today quick-add suggestion chips (FTY-341).
 *
 * A quiet, horizontally-scrollable row above the composer showing what the user
 * most plausibly wants to log right now, per FTY-340's time-aware ranking. The
 * client renders the server order verbatim — no client-side ranking or
 * filtering. Tapping a chip prefills + focuses the composer (one more tap to
 * submit keeps logging deliberate); the parent decides how a `saved_food_id`
 * suggestion applies (the FTY-053 estimator-skip path).
 *
 * Returns null — occupying no space, no empty shell — when there is nothing to
 * suggest, so a zero-suggestion or failed fetch leaves the composer fully usable
 * with no placeholder row.
 */
export function QuickAddChips({
  suggestions,
  onSelect,
}: {
  /** Ranked suggestions in canonical server order. */
  suggestions: readonly FoodSuggestionDTO[];
  /** Called with the tapped suggestion; the parent prefills/focuses/applies. */
  onSelect: (suggestion: FoodSuggestionDTO) => void;
}) {
  if (suggestions.length === 0) {
    return null;
  }

  return (
    <ScrollView
      testID="quick-add-chips"
      horizontal
      // A whole row a VoiceOver user can swipe past in one move, rather than
      // wading through every chip before reaching the composer.
      accessibilityRole="list"
      accessibilityLabel="Quick-add suggestions"
      style={styles.row}
      showsHorizontalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={styles.rowContent}
    >
      {suggestions.map((suggestion, index) => (
        <Chip
          // Labels can repeat across a saved food and its history, so the id (or
          // its index) disambiguates the key without affecting render order.
          key={`${suggestion.saved_food_id ?? "history"}-${index}`}
          label={suggestion.label}
          accessibilityLabel={`Suggestion: ${suggestion.label}`}
          onPress={() => onSelect(suggestion)}
        />
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  row: {
    flexGrow: 0,
    marginBottom: spacing.sm,
  },
  rowContent: {
    gap: spacing.sm,
    alignItems: "center",
  },
});
