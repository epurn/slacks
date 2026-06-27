import { useEffect, useState } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
} from "react-native";

import {
  searchSavedFoods as searchSavedFoodsApi,
  type SavedFoodDTO,
  type SavedFoodSession,
} from "@/api/savedFoods";

/** Debounce window in ms: avoids a network call per keystroke. */
const DEBOUNCE_MS = 300;

/**
 * A keyboard-style saved-food suggestion strip (FTY-053).
 *
 * Renders directly below the log-entry text input. As the user types, it
 * debounced-queries the FTY-052 typeahead endpoint and shows prefix-matching
 * saved foods as tappable chips. Tapping a chip calls `onSelect` with the
 * saved food; the parent decides how to apply the stored values.
 *
 * Returns null (occupies no space) when: no session, empty query, or no
 * matches for the current query. The backend owns prefix-match semantics —
 * the UI applies no additional client-side filtering.
 *
 * `search` is injectable for tests so no real network call is made.
 */
export function TypeaheadSuggestionBar({
  query,
  session,
  onSelect,
  search = searchSavedFoodsApi,
}: {
  /** The current text in the log-entry input; queried after debounce. */
  query: string;
  /** The authenticated session, or null when no user is signed in. */
  session: SavedFoodSession | null;
  /** Called when the user taps a suggestion. */
  onSelect: (food: SavedFoodDTO) => void;
  /** Injectable search function for tests. */
  search?: typeof searchSavedFoodsApi;
}) {
  const [suggestions, setSuggestions] = useState<readonly SavedFoodDTO[]>([]);
  const trimmed = query.trim();

  // Suggestions are only valid when there is a session and a non-empty query.
  // Deriving this avoids a synchronous `setSuggestions([])` call inside an
  // effect, which the lint rule flags as a potential cascading-render source.
  const visibleSuggestions = session && trimmed.length > 0 ? suggestions : [];

  useEffect(() => {
    if (!session || trimmed.length === 0) return;

    const timer = setTimeout(() => {
      void search(session, trimmed).then(
        (response) => setSuggestions(response.items),
        // Silently fail — a transient search error must not disrupt the main
        // log flow; the suggestions just disappear until the next keystroke.
        () => setSuggestions([]),
      );
    }, DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [session, trimmed, search]);

  if (visibleSuggestions.length === 0) {
    return null;
  }

  return (
    <ScrollView
      horizontal
      style={styles.bar}
      showsHorizontalScrollIndicator={false}
      keyboardShouldPersistTaps="handled"
      contentContainerStyle={styles.barContent}
    >
      {visibleSuggestions.map((food) => (
        <Pressable
          key={food.id}
          style={styles.chip}
          accessibilityRole="button"
          accessibilityLabel={`Use saved food: ${food.name}`}
          onPress={() => onSelect(food)}
        >
          <Text style={styles.chipText} numberOfLines={1}>
            {food.name}
          </Text>
        </Pressable>
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  bar: {
    flexGrow: 0,
    marginTop: 6,
  },
  barContent: {
    paddingRight: 4,
  },
  chip: {
    backgroundColor: "#E4E4EA",
    borderRadius: 18,
    paddingVertical: 6,
    paddingHorizontal: 14,
    marginRight: 8,
    justifyContent: "center",
    alignItems: "center",
  },
  chipText: {
    fontSize: 14,
    color: "#1C1C1E",
    fontWeight: "500",
  },
});
