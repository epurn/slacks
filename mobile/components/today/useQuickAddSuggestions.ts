import { useCallback, useEffect, useState } from "react";
import { type TextInput } from "react-native";

import {
  getFoodSuggestions as getFoodSuggestionsApi,
  type FoodSuggestionDTO,
} from "@/api/foodSuggestions";
import {
  searchSavedFoods as searchSavedFoodsApi,
  type SavedFoodDTO,
} from "@/api/savedFoods";
import { type ApiSession } from "@/state/session";

/**
 * Owns Today's quick-add suggestion chips (FTY-341): fetching the FTY-340
 * time-aware ranking and turning a chip tap into a deliberate prefill.
 *
 * Fetch cadence is focus-driven, never a polling timer: the row refreshes when
 * the screen becomes active (`isActive` rising edge, incl. the initial mount)
 * and again after a successful submit (`refreshSuggestions`, wired to the submit
 * machine's reconcile), because the just-logged item can change the ranking. A
 * failed fetch is swallowed to an empty list, so the row silently absents and
 * never blocks the composer; the last successful fetch is kept in memory across
 * a transient failure until the next refresh replaces it (no offline cache).
 *
 * Tap behaviour keeps logging deliberate — the chip prefills the composer with
 * the suggestion's phrase and focuses it, one more tap to submit. A
 * `saved_food_id` suggestion additionally hydrates the selected saved food (via
 * the FTY-052 typeahead search, matched by id) so the subsequent submit routes
 * through the FTY-053 estimator-skip apply path; if that lookup fails the chip
 * still prefills and the submit falls back to the normal estimator path.
 */
export function useQuickAddSuggestions({
  apiSession,
  isActive,
  getSuggestions = getFoodSuggestionsApi,
  searchSavedFoods = searchSavedFoodsApi,
  setText,
  inputRef,
  setSelectedSavedFood,
}: {
  apiSession: ApiSession | null;
  /** The screen's foreground+focused signal; a rising edge triggers a refresh. */
  isActive: boolean;
  getSuggestions?: typeof getFoodSuggestionsApi;
  searchSavedFoods?: typeof searchSavedFoodsApi;
  setText: (value: string) => void;
  inputRef: React.RefObject<TextInput | null>;
  setSelectedSavedFood: (food: SavedFoodDTO | null) => void;
}): {
  suggestions: readonly FoodSuggestionDTO[];
  refreshSuggestions: () => void;
  handleSelectSuggestion: (suggestion: FoodSuggestionDTO) => void;
} {
  const [suggestions, setSuggestions] = useState<readonly FoodSuggestionDTO[]>(
    [],
  );

  // Fetch on the focus edge (and initial mount): the effect re-runs when the
  // screen becomes active, keeping the row fresh without a background timer. On
  // failure the row silently absents (empty list) — the composer is never
  // blocked on suggestions. `active` guards a late resolve after unfocus/unmount.
  useEffect(() => {
    if (!apiSession || !isActive) return;
    let active = true;
    getSuggestions(apiSession).then(
      (response) => {
        if (active) setSuggestions(response.items);
      },
      () => {
        if (active) setSuggestions([]);
      },
    );
    return () => {
      active = false;
    };
  }, [apiSession, isActive, getSuggestions]);

  // Refresh after a successful submit — the just-logged item's rank changes.
  // A one-shot read (no cancellation needed) that replaces the row in place.
  const refreshSuggestions = useCallback(() => {
    if (!apiSession) return;
    getSuggestions(apiSession).then(
      (response) => setSuggestions(response.items),
      () => setSuggestions([]),
    );
  }, [apiSession, getSuggestions]);

  const handleSelectSuggestion = useCallback(
    (suggestion: FoodSuggestionDTO) => {
      // Prefill + focus — never an accidental one-tap log from a mis-tap on a
      // scrolling row. The next tap on "Add" is what submits.
      setText(suggestion.submit_phrase);
      inputRef.current?.focus();
      if (!suggestion.saved_food_id || !apiSession) return;
      // Hydrate the saved food so the subsequent submit skips the estimator
      // (FTY-053). The label is the saved food's own name, so a contains-match
      // search surfaces it; we pick the exact id. A miss/failure leaves the
      // composer prefilled and falls back to the normal estimator submit.
      const savedFoodId = suggestion.saved_food_id;
      void searchSavedFoods(apiSession, suggestion.label).then(
        (response) => {
          const match = response.items.find((food) => food.id === savedFoodId);
          if (match) setSelectedSavedFood(match);
        },
        () => {
          // Swallow: never block the composer on a hydration failure.
        },
      );
    },
    [apiSession, searchSavedFoods, setText, inputRef, setSelectedSavedFood],
  );

  return { suggestions, refreshSuggestions, handleSelectSuggestion };
}
