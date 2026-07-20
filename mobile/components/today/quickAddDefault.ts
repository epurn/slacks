import { type FoodSuggestionDTO } from "@/api/foodSuggestions";
import { normalizeText } from "@/utils/normalizeText";

/**
 * Pick the quick-add default (FTY-408): the user's own prior food to offer when
 * the typed name matches one they have logged before.
 *
 * The candidate pool is the already-fetched FTY-340 suggestions — the user's own
 * saved foods and completed food-log history, owner-scoped by the bearer token
 * (`docs/contracts/food-suggestions.md`), so there is no cross-user leakage. A
 * food the user hand-corrected is a completed history row, so it is in this pool;
 * quick-adding it re-submits its phrase through the estimator, where FTY-406's
 * prior-correction tier resolves it to the corrected value.
 *
 * Only **history-only** candidates (`saved_food_id === null`) are considered:
 * a saved food is already offered by the saved-food typeahead
 * (`TypeaheadSuggestionBar`, FTY-053), and folding it in here would double it.
 * That leaves exactly the corrected/logged-but-not-saved foods the typeahead
 * misses.
 *
 * Matching is name-normalized with the shared saved-food rule (the same rule
 * FTY-406 keys its lookup on): an exact normalized-name match is the default;
 * otherwise the first history candidate whose normalized label starts with the
 * normalized typed text is offered, so the default can surface before the whole
 * name is typed. No match (or empty query) returns `null`, so a name with no
 * matching history leaves the composer exactly as it is today.
 */
export function matchQuickAddDefault(
  query: string,
  suggestions: readonly FoodSuggestionDTO[],
): FoodSuggestionDTO | null {
  const normalizedQuery = normalizeText(query);
  if (normalizedQuery.length === 0) return null;

  const priorFoods = suggestions.filter(
    (suggestion) => suggestion.saved_food_id === null,
  );

  const exact = priorFoods.find(
    (suggestion) => normalizeText(suggestion.label) === normalizedQuery,
  );
  if (exact) return exact;

  return (
    priorFoods.find((suggestion) =>
      normalizeText(suggestion.label).startsWith(normalizedQuery),
    ) ?? null
  );
}
