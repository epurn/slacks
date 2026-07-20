/**
 * FTY-204: Correction-sheet state hook.
 *
 * Owns every mode transition, the four levers' async handlers, and the
 * save/override/change-match status transitions for the correction sheet,
 * extracted from the former monolithic `CorrectionSheet.tsx`. The sheet shell
 * becomes a thin renderer over what this returns. Behaviour — including the
 * search debounce + out-of-order guard, the optimistic-revert on failure, and
 * the Beat-2 correction-saved pulse/haptic firing only on a successful commit —
 * is unchanged.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  listSourceCandidates as listSourceCandidatesApi,
  reResolveItem as reResolveItemApi,
  type PickableCandidate,
  type PriorCorrectionCandidate,
  type SourceCandidate,
} from "@/api/corrections";
import {
  editDerivedItem as editDerivedItemApi,
  MAX_ITEM_NAME_LENGTH,
  renameDerivedItem as renameDerivedItemApi,
  type DerivedFoodItemDTO,
  type DerivedItem,
} from "@/api/derivedItems";
import {
  saveFood as saveFoodApi,
  type NutritionSnapshot,
} from "@/api/savedFoods";
import { formatValue } from "@/state/derivedItems";
import type { ApiSession } from "@/state/session";
import { correctionSavedHaptic } from "@/theme/haptics";
import { usePulse } from "@/theme/motion";

import { SEARCH_DEBOUNCE_MS, messageForError } from "./helpers";
import type { SaveFoodStatus } from "./SaveFoodRow";

export type SheetMode =
  | "normal"
  | "change-match"
  | "override"
  | "clarify"
  // FTY-312: the `Make it exact` exact-evidence sub-flow (barcode/label →
  // preview → apply-in-place). Its own step state lives in `useExactEvidence`.
  | "make-exact"
  // FTY-378: in-sheet display-name rename (the FTY-377 audited name edit).
  | "rename";

/** The override draft the "confirm_apply" seam pre-fills: the item's current calories. */
function seamOverrideDraft(item: DerivedItem): string {
  return item.item_type === "food" ? formatValue(item.calories) : "";
}

export interface UseCorrectionSheetArgs {
  initialItem: DerivedItem;
  visible: boolean;
  session: ApiSession;
  onItemChange?: (item: DerivedItem) => void;
  logPhrase?: string;
  needsClarification: boolean;
  onClarificationResolved?: (answer: string) => void;
  editItem: typeof editDerivedItemApi;
  renameItem: typeof renameDerivedItemApi;
  listCandidates: typeof listSourceCandidatesApi;
  reResolve: typeof reResolveItemApi;
  saveFood: typeof saveFoodApi;
  /**
   * E2E-only: opens the sheet directly into this mode instead of "normal"
   * (FTY-263 visual-review seam). `undefined` for every real caller, so
   * default behaviour is unchanged outside the visual-review harness.
   */
  initialMode?: SheetMode;
}

export function useCorrectionSheet({
  initialItem,
  visible,
  session,
  onItemChange,
  logPhrase,
  needsClarification,
  onClarificationResolved,
  editItem,
  renameItem,
  listCandidates,
  reResolve,
  saveFood,
  initialMode,
}: UseCorrectionSheetArgs) {
  // Beat 2 — correction saved. A brief confirmation pulse + success haptic fires
  // once per *successful* commit (amount step, re-resolve, value override), never
  // on a validation error or an API failure.
  const { scale, opacity, pulse } = usePulse();
  const fireCorrectionSaved = useCallback(() => {
    correctionSavedHaptic();
    pulse();
  }, [pulse]);

  const [item, setItem] = useState<DerivedItem>(initialItem);

  // Resync local item when prop changes (parent may push a confirmed edit).
  const [syncedItem, setSyncedItem] = useState<DerivedItem>(initialItem);
  if (initialItem !== syncedItem) {
    setSyncedItem(initialItem);
    setItem(initialItem);
  }

  // Sheet opens in clarify-mode when needs_clarification, in the seam's
  // requested mode when present (FTY-263), otherwise normal.
  const defaultMode = initialMode ?? (needsClarification ? "clarify" : "normal");
  const [mode, setMode] = useState<SheetMode>(defaultMode);

  // Sync mode when needsClarification prop changes or sheet re-opens.
  const [syncedNeedsClarification, setSyncedNeedsClarification] = useState(needsClarification);
  if (needsClarification !== syncedNeedsClarification) {
    setSyncedNeedsClarification(needsClarification);
    setMode(defaultMode);
  }

  // The Change-match, advanced-override, or rename panel wants the large detent
  // (each opens a keyboard or a search). Narrowing the allowed detents to
  // large-only makes UIKit animate the sheet up to it; the quick-fix path
  // (amount / save / clarify) stays at the medium detent with the timeline
  // visible behind.
  const expanded =
    mode === "change-match" ||
    mode === "override" ||
    mode === "make-exact" ||
    mode === "rename";

  // ─── Amount stepper state ───────────────────────────────────────────────────
  const [amountPending, setAmountPending] = useState(false);
  const [amountError, setAmountError] = useState<string | null>(null);

  // ─── Change-match state ─────────────────────────────────────────────────────
  const [candidates, setCandidates] = useState<readonly SourceCandidate[]>([]);
  // FTY-407: the acting user's own prior corrections for this item's name,
  // ranked above the guessed-source `candidates`. Empty ⇒ no matching history.
  const [priorCorrections, setPriorCorrections] = useState<
    readonly PriorCorrectionCandidate[]
  >([]);
  const [candidatesLoading, setCandidatesLoading] = useState(false);
  const [candidatesError, setCandidatesError] = useState<string | null>(null);
  const [matchQuery, setMatchQuery] = useState("");
  const [reResolving, setReResolving] = useState(false);
  const [reResolveError, setReResolveError] = useState<string | null>(null);
  // Debounce timer + monotonic request id for the change-match search. The id
  // guards against out-of-order responses: a slower earlier query that resolves
  // after a newer one must not overwrite the newer query's candidates.
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const searchSeq = useRef(0);

  // ─── Override (advanced) state ──────────────────────────────────────────────
  const [overrideField, setOverrideField] = useState<string>("calories");
  // The seam's "confirm_apply" preset opens straight into override mode with the
  // item's current calories pre-filled — a value ready to confirm/apply, not a
  // blank input (FTY-263). Every real caller has no `initialMode`, so this stays
  // "" as before.
  const [overrideDraft, setOverrideDraft] = useState(
    initialMode === "override" ? seamOverrideDraft(initialItem) : "",
  );
  const [overrideSaving, setOverrideSaving] = useState(false);
  const [overrideError, setOverrideError] = useState<string | null>(null);

  // ─── Rename state (FTY-378) ─────────────────────────────────────────────────
  const [renameDraft, setRenameDraft] = useState("");
  const [renameSaving, setRenameSaving] = useState(false);
  const [renameError, setRenameError] = useState<string | null>(null);

  // ─── Clarify state ──────────────────────────────────────────────────────────
  const [clarifyText, setClarifyText] = useState("");
  const [clarifySubmitting, setClarifySubmitting] = useState(false);

  // ─── Save as food state ─────────────────────────────────────────────────────
  const [saveFoodStatus, setSaveFoodStatus] = useState<SaveFoodStatus>("idle");
  const [saveFoodError, setSaveFoodError] = useState<string | null>(null);

  // Reset transient state when the sheet re-opens (visible transitions false→true).
  // Uses the "adjust state on prop change during render" pattern (no useEffect)
  // to avoid the setState-in-effect lint rule and prevent cascading renders.
  const [prevVisible, setPrevVisible] = useState(visible);
  if (visible !== prevVisible) {
    setPrevVisible(visible);
    if (visible) {
      setMode(defaultMode);
      setAmountError(null);
      setCandidates([]);
      setPriorCorrections([]);
      setCandidatesError(null);
      setMatchQuery("");
      setReResolveError(null);
      setOverrideDraft(defaultMode === "override" ? seamOverrideDraft(item) : "");
      setOverrideError(null);
      setRenameDraft("");
      setRenameError(null);
      setClarifyText("");
      setSaveFoodStatus("idle");
      setSaveFoodError(null);
    }
  }

  // ─── Amount stepper ─────────────────────────────────────────────────────────

  const handleAmountStep = useCallback(
    async (delta: number) => {
      if (item.item_type !== "food") return;
      const food = item as DerivedFoodItemDTO;
      const current = food.amount ?? 1;
      const next = Math.max(0.25, Math.round((current + delta) * 4) / 4);
      if (next === current) return;

      const prior = item;
      setAmountPending(true);
      setAmountError(null);
      try {
        const updated = await editItem(session, "food", food.id, "quantity", next);
        setItem(updated);
        onItemChange?.(updated);
        fireCorrectionSaved();
      } catch (err) {
        setItem(prior);
        setAmountError(messageForError(err, "adjust the amount"));
      } finally {
        setAmountPending(false);
      }
    },
    [item, editItem, session, onItemChange, fireCorrectionSaved],
  );

  // ─── Change match ────────────────────────────────────────────────────────────

  // Cancel any pending debounced search and invalidate in-flight responses so a
  // late result can't land after we've moved on (leaving the panel, picking).
  const cancelPendingSearch = useCallback(() => {
    if (searchTimer.current) {
      clearTimeout(searchTimer.current);
      searchTimer.current = null;
    }
    searchSeq.current += 1;
  }, []);

  const loadCandidates = useCallback(
    async (query?: string) => {
      if (item.item_type !== "food") return;
      const food = item as DerivedFoodItemDTO;
      const seq = (searchSeq.current += 1);
      setCandidatesLoading(true);
      setCandidatesError(null);
      try {
        const results = await listCandidates(session, food.id, query || undefined);
        if (seq !== searchSeq.current) return; // superseded by a newer query
        setCandidates(results.candidates);
        setPriorCorrections(results.priorCorrections);
      } catch (err) {
        if (seq !== searchSeq.current) return; // superseded by a newer query
        setCandidatesError(messageForError(err, "load alternatives"));
        setCandidates([]);
        setPriorCorrections([]);
      } finally {
        if (seq === searchSeq.current) setCandidatesLoading(false);
      }
    },
    [item, listCandidates, session],
  );

  const openChangeMatch = useCallback(() => {
    setMode("change-match");
    setReResolveError(null);
    void loadCandidates();
  }, [loadCandidates]);

  // Seam-only: the "typeahead" preset (FTY-263) opens straight into change-match
  // mode without going through `openChangeMatch`, so the candidate list would
  // otherwise sit empty. Fires once per mounted sheet instance — `initialMode` is
  // fixed for the hook's lifetime (set once by the caller's props), never toggled
  // by user interaction — so this can never re-fire mid-session. Deferred to a
  // microtask (not called synchronously in the effect body) so `loadCandidates`'s
  // own setState calls never run in the same commit as this effect.
  useEffect(() => {
    if (initialMode !== "change-match") return;
    queueMicrotask(() => void loadCandidates());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleCandidateSearch = useCallback(
    (query: string) => {
      setMatchQuery(query);
      if (searchTimer.current) clearTimeout(searchTimer.current);
      searchTimer.current = setTimeout(() => {
        searchTimer.current = null;
        void loadCandidates(query);
      }, SEARCH_DEBOUNCE_MS);
    },
    [loadCandidates],
  );

  const handlePickCandidate = useCallback(
    async (candidate: PickableCandidate) => {
      if (item.item_type !== "food") return;
      const food = item as DerivedFoodItemDTO;
      cancelPendingSearch();
      setReResolving(true);
      setReResolveError(null);
      try {
        // A prior-correction candidate applies through the same re-resolve path:
        // its `source_ref` (`prior_correction:<hash>`) is the re-derivable handle
        // the server recognizes (FTY-411 apply branch).
        const updated = await reResolve(session, food.id, candidate.source_ref);
        setItem(updated);
        onItemChange?.(updated);
        setMode("normal");
        setMatchQuery("");
        setCandidates([]);
        setPriorCorrections([]);
        fireCorrectionSaved();
      } catch (err) {
        setReResolveError(messageForError(err, "apply that match"));
      } finally {
        setReResolving(false);
      }
    },
    [item, reResolve, session, onItemChange, cancelPendingSearch, fireCorrectionSaved],
  );

  const cancelChangeMatch = useCallback(() => {
    cancelPendingSearch();
    setMode("normal");
    setMatchQuery("");
    setCandidates([]);
    setPriorCorrections([]);
    setCandidatesError(null);
  }, [cancelPendingSearch]);

  // ─── Make it exact (FTY-312) ─────────────────────────────────────────────────

  // Open / leave the exact-evidence sub-flow. The barcode/label capture, proposal
  // preview, and per-step async live in `useExactEvidence` (keyed on this mode);
  // the sheet only owns the mode transition and the shared in-place commit.
  const openMakeExact = useCallback(() => setMode("make-exact"), []);
  const cancelMakeExact = useCallback(() => setMode("normal"), []);

  // Commit an applied exact-evidence proposal to the same item in place: adopt the
  // server-returned item, notify the parent, return to the normal sheet with the
  // new provenance visible, and fire the same correction-saved beat as an
  // amount/change-match edit. Never runs client nutrition math — the item comes
  // straight from `apply`.
  const commitExactUpgrade = useCallback(
    (updated: DerivedFoodItemDTO) => {
      setItem(updated);
      onItemChange?.(updated);
      setMode("normal");
      fireCorrectionSaved();
    },
    [onItemChange, fireCorrectionSaved],
  );

  // ─── Advanced override ───────────────────────────────────────────────────────

  const openOverride = useCallback((field: string, currentValue: number | null) => {
    setOverrideField(field);
    setOverrideDraft(currentValue !== null ? formatValue(currentValue) : "");
    setOverrideError(null);
    setMode("override");
  }, []);

  const submitOverride = useCallback(async () => {
    if (item.item_type !== "food") return;
    const food = item as DerivedFoodItemDTO;
    const parsed = Number(overrideDraft.trim());
    if (overrideDraft.trim() === "" || !Number.isFinite(parsed) || parsed < 0) {
      setOverrideError("Enter a number that's zero or more.");
      return;
    }
    const prior = item;
    setOverrideSaving(true);
    setOverrideError(null);
    try {
      const updated = await editItem(session, "food", food.id, overrideField, parsed);
      setItem(updated);
      onItemChange?.(updated);
      setMode("normal");
      setOverrideDraft("");
      fireCorrectionSaved();
    } catch (err) {
      setItem(prior);
      setOverrideError(messageForError(err, "save that override"));
    } finally {
      setOverrideSaving(false);
    }
  }, [item, editItem, session, onItemChange, overrideField, overrideDraft, fireCorrectionSaved]);

  const cancelOverride = useCallback(() => {
    setMode("normal");
    setOverrideDraft("");
    setOverrideError(null);
  }, []);

  // ─── Rename (FTY-378) ────────────────────────────────────────────────────────

  const openRename = useCallback(() => {
    setRenameDraft(item.name);
    setRenameError(null);
    setMode("rename");
  }, [item.name]);

  // Client-side gate mirroring the backend bound: a trimmed, non-empty, changed
  // name within the 200-char column limit. The backend stays authoritative — a
  // 422 renders as calm, content-free copy below.
  const renameTrimmed = renameDraft.trim();
  const renameCanSave =
    !renameSaving &&
    renameTrimmed !== "" &&
    renameTrimmed !== item.name &&
    renameTrimmed.length <= MAX_ITEM_NAME_LENGTH;

  const submitRename = useCallback(async () => {
    const trimmed = renameDraft.trim();
    if (
      renameSaving ||
      trimmed === "" ||
      trimmed === item.name ||
      trimmed.length > MAX_ITEM_NAME_LENGTH
    ) {
      return;
    }
    const prior = item;
    setRenameSaving(true);
    setRenameError(null);
    try {
      const updated = await renameItem(session, item.item_type, item.id, trimmed);
      setItem(updated);
      onItemChange?.(updated);
      setMode("normal");
      setRenameDraft("");
      fireCorrectionSaved();
    } catch (err) {
      // Revert to the prior item and stay in rename mode so the user can retry;
      // the error copy never contains the typed name (status + action only).
      setItem(prior);
      setRenameError(messageForError(err, "rename this item"));
    } finally {
      setRenameSaving(false);
    }
  }, [item, renameDraft, renameSaving, renameItem, session, onItemChange, fireCorrectionSaved]);

  const cancelRename = useCallback(() => {
    setMode("normal");
    setRenameDraft("");
    setRenameError(null);
  }, []);

  // ─── Clarify ─────────────────────────────────────────────────────────────────

  const handleClarifyAnswer = useCallback(
    (answer: string) => {
      if (!answer.trim()) return;
      setClarifySubmitting(true);
      try {
        onClarificationResolved?.(answer.trim());
      } finally {
        setClarifySubmitting(false);
      }
    },
    [onClarificationResolved],
  );

  // ─── Save as food ─────────────────────────────────────────────────────────────

  const handleSaveFood = useCallback(async () => {
    if (item.item_type !== "food" || !logPhrase) return;
    const food = item as DerivedFoodItemDTO;
    if (food.calories === null) return;

    const nutrition: NutritionSnapshot = {
      calories: food.calories,
      protein_g: food.protein_g,
      carbs_g: food.carbs_g,
      fat_g: food.fat_g,
      serving_size: food.amount ?? 1,
      serving_unit: food.unit ?? "serving",
    };
    setSaveFoodStatus("saving");
    setSaveFoodError(null);
    try {
      await saveFood(session, { name: food.name, phrase: logPhrase, nutrition });
      setSaveFoodStatus("saved");
    } catch {
      setSaveFoodStatus("error");
      setSaveFoodError("We couldn't save that food. Check your connection and try again.");
    }
  }, [item, logPhrase, saveFood, session]);

  return {
    // Presentation motion (Beat 2)
    scale,
    opacity,
    // Item + mode
    item,
    mode,
    expanded,
    // Amount stepper
    amountPending,
    amountError,
    handleAmountStep,
    // Change match
    candidates,
    priorCorrections,
    candidatesLoading,
    candidatesError,
    matchQuery,
    reResolving,
    reResolveError,
    openChangeMatch,
    handleCandidateSearch,
    handlePickCandidate,
    cancelChangeMatch,
    // Make it exact (FTY-312)
    openMakeExact,
    cancelMakeExact,
    commitExactUpgrade,
    // Advanced override
    overrideField,
    overrideDraft,
    overrideSaving,
    overrideError,
    setOverrideDraft,
    openOverride,
    submitOverride,
    cancelOverride,
    // Rename (FTY-378)
    renameDraft,
    renameSaving,
    renameError,
    renameCanSave,
    setRenameDraft,
    openRename,
    submitRename,
    cancelRename,
    // Clarify
    clarifyText,
    setClarifyText,
    clarifySubmitting,
    handleClarifyAnswer,
    // Save as food
    saveFoodStatus,
    saveFoodError,
    handleSaveFood,
  };
}
