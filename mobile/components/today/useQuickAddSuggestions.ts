import { useCallback, useEffect, useRef, useState } from "react";
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
 *
 * That hydration is async while the composer stays immediately submittable, so
 * the submit path must join it rather than race it: the returned `handleSubmit`
 * first gives visible acknowledgement (cleared composer + disabled Add), then
 * awaits an in-flight lookup and writes the match into `selectedSavedFoodRef`
 * before the machine reads it, so a fast chip tap + Add still takes the
 * estimator-skip path. Every chip tap
 * first clears the previous selection and invalidates any earlier in-flight
 * lookup (the tap replaced the composer text, so a stale resolve must never
 * attach the wrong saved food). Manual composer edits do the same invalidation
 * because edited text is no longer the saved-food chip the user selected, and
 * the returned `selectSavedFood` gives the FTY-053 typeahead the same supersede
 * power over an in-flight chip hydration.
 */
export function useQuickAddSuggestions({
  apiSession,
  isActive,
  getSuggestions = getFoodSuggestionsApi,
  searchSavedFoods = searchSavedFoodsApi,
  setText,
  setSubmitting,
  inputRef,
  setSelectedSavedFood,
  selectedSavedFoodRef,
  submitLogEntry,
}: {
  apiSession: ApiSession | null;
  /** The screen's foreground+focused signal; a rising edge triggers a refresh. */
  isActive: boolean;
  getSuggestions?: typeof getFoodSuggestionsApi;
  searchSavedFoods?: typeof searchSavedFoodsApi;
  setText: (value: string) => void;
  setSubmitting: (value: boolean) => void;
  inputRef: React.RefObject<TextInput | null>;
  setSelectedSavedFood: (food: SavedFoodDTO | null) => void;
  /**
   * The submit machine's synchronous read of the selection (see useTodayData).
   * The submit join writes a freshly hydrated match here directly, because the
   * machine reads it before the queued state update could ever re-render.
   */
  selectedSavedFoodRef: React.MutableRefObject<SavedFoodDTO | null>;
  /** The submit machine's entry point that `handleSubmit` wraps with the join. */
  submitLogEntry: () => Promise<void>;
}): {
  suggestions: readonly FoodSuggestionDTO[];
  refreshSuggestions: () => void;
  handleSelectSuggestion: (suggestion: FoodSuggestionDTO) => void;
  handleComposerTextChange: (value: string) => void;
  handleSubmit: () => Promise<void>;
  selectSavedFood: (food: SavedFoodDTO | null) => void;
} {
  const [suggestions, setSuggestions] = useState<readonly FoodSuggestionDTO[]>(
    [],
  );
  // Monotonic fetch counter shared by the focus effect and the post-submit
  // refresh: only the latest request's response may land, so two in-flight
  // reads (focus edge racing a submit refresh) can never apply out of order.
  const fetchSeq = useRef(0);
  // The saved-food hydration for the most recent chip tap, or null. The
  // promise is normalized to never reject (miss/failure → null). Identity is
  // the validity token: a newer tap or a typeahead selection replaces/clears
  // the record, so a stale resolve (or a stale submit join) detects it is no
  // longer the live lookup and applies nothing. `settled` flips once the
  // lookup has resolved and applied its result to the selection state — from
  // then on submits take the ordinary synchronous path again.
  const pendingSavedFoodLookup = useRef<{
    promise: Promise<SavedFoodDTO | null>;
    settled: boolean;
  } | null>(null);

  // Fetch on the focus edge (and initial mount): the effect re-runs when the
  // screen becomes active, keeping the row fresh without a background timer. On
  // failure the row silently absents (empty list) — the composer is never
  // blocked on suggestions. `active` guards a late resolve after unfocus/unmount.
  useEffect(() => {
    if (!apiSession || !isActive) return;
    let active = true;
    const seq = ++fetchSeq.current;
    getSuggestions(apiSession).then(
      (response) => {
        if (active && fetchSeq.current === seq) setSuggestions(response.items);
      },
      () => {
        if (active && fetchSeq.current === seq) setSuggestions([]);
      },
    );
    return () => {
      active = false;
    };
  }, [apiSession, isActive, getSuggestions]);

  // Refresh after a successful submit — the just-logged item's rank changes.
  // A one-shot read that replaces the row in place unless a newer fetch has
  // started since (the sequence guard keeps responses in order).
  const refreshSuggestions = useCallback(() => {
    if (!apiSession) return;
    const seq = ++fetchSeq.current;
    getSuggestions(apiSession).then(
      (response) => {
        if (fetchSeq.current === seq) setSuggestions(response.items);
      },
      () => {
        if (fetchSeq.current === seq) setSuggestions([]);
      },
    );
  }, [apiSession, getSuggestions]);

  const handleSelectSuggestion = useCallback(
    (suggestion: FoodSuggestionDTO) => {
      // Prefill + focus — never an accidental one-tap log from a mis-tap on a
      // scrolling row. The next tap on "Add" is what submits.
      setText(suggestion.submit_phrase);
      inputRef.current?.focus();
      // The tap replaced the composer text, so any previous saved-food
      // association — an earlier chip's hydrated selection or its still
      // in-flight lookup — no longer describes what will be submitted.
      setSelectedSavedFood(null);
      pendingSavedFoodLookup.current = null;
      selectedSavedFoodRef.current = null;
      if (!suggestion.saved_food_id || !apiSession) return;
      // Hydrate the saved food so the subsequent submit skips the estimator
      // (FTY-053). The label is the saved food's own name, so a contains-match
      // search surfaces it; we pick the exact id. A miss/failure leaves the
      // composer prefilled and falls back to the normal estimator submit.
      const savedFoodId = suggestion.saved_food_id;
      const entry: { settled: boolean; promise: Promise<SavedFoodDTO | null> } = {
        settled: false,
        promise: searchSavedFoods(apiSession, suggestion.label)
          .then(
            (response) =>
              response.items.find((food) => food.id === savedFoodId) ?? null,
            // Swallow: never block the composer on a hydration failure.
            () => null,
          )
          .then((match) => {
            // Apply only while this is still the live lookup — a newer tap (or
            // a typeahead selection) has replaced it otherwise, and a stale
            // resolve must not attach the wrong saved food to the current text.
            if (pendingSavedFoodLookup.current !== entry) return null;
            entry.settled = true;
            if (match) {
              selectedSavedFoodRef.current = match;
              setSelectedSavedFood(match);
            }
            return match;
          }),
      };
      pendingSavedFoodLookup.current = entry;
    },
    [
      apiSession,
      searchSavedFoods,
      setText,
      inputRef,
      setSelectedSavedFood,
      selectedSavedFoodRef,
    ],
  );

  // Submit-time join (FTY-053 guarantee): the composer is submittable the
  // instant a chip prefills it, so the submit visibly acknowledges the tap
  // before awaiting an in-flight hydration instead of racing it, writing the
  // match into the ref the machine reads.
  // A lookup that already settled applied its result to the selection state,
  // and the common no-chip submit has nothing to join — both keep the fully
  // synchronous path (and its same-tick optimistic acknowledgement). A miss,
  // failure, or supersession (a newer tap replaced the lookup while awaited;
  // its own resolve owns the result) submits down the normal estimator path.
  // `joiningSubmit` collapses a double tap during the join window, which the
  // machine's own `submitting` guard cannot see (it only closes over state
  // from completed renders).
  const joiningSubmit = useRef(false);
  const handleComposerTextChange = useCallback(
    (value: string) => {
      pendingSavedFoodLookup.current = null;
      selectedSavedFoodRef.current = null;
      setSelectedSavedFood(null);
      setText(value);
    },
    [selectedSavedFoodRef, setSelectedSavedFood, setText],
  );

  const handleSubmit = useCallback(async () => {
    if (joiningSubmit.current) return;
    const pending = pendingSavedFoodLookup.current;
    if (!pending || pending.settled) {
      await submitLogEntry();
      return;
    }
    joiningSubmit.current = true;
    setText("");
    setSubmitting(true);
    try {
      const match = await pending.promise;
      if (match && pendingSavedFoodLookup.current === pending) {
        selectedSavedFoodRef.current = match;
      }
      await submitLogEntry();
    } finally {
      joiningSubmit.current = false;
    }
  }, [setText, setSubmitting, submitLogEntry, selectedSavedFoodRef]);

  // A deliberate FTY-053 typeahead selection supersedes an in-flight chip
  // hydration — without this, a stale chip lookup resolving after the
  // selection (or joined at submit time) could overwrite the explicit pick.
  const selectSavedFood = useCallback(
    (food: SavedFoodDTO | null) => {
      pendingSavedFoodLookup.current = null;
      selectedSavedFoodRef.current = food;
      setSelectedSavedFood(food);
    },
    [selectedSavedFoodRef, setSelectedSavedFood],
  );

  return {
    suggestions,
    refreshSuggestions,
    handleSelectSuggestion,
    handleComposerTextChange,
    handleSubmit,
    selectSavedFood,
  };
}
