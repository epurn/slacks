/**
 * FTY-100: Universal detail / correction sheet.
 *
 * A slide-up sheet (a `Modal` with `animationType="slide"`) that opens from any
 * timeline item and provides four ordered levers for correction:
 *
 *   1. Amount stepper (primary) — provenance-preserving portion adjust (FTY-092)
 *   2. "Change match" — alternative source search + re-resolve (FTY-093)
 *   3. Advanced value override — direct field edit marking item user-edited (FTY-051)
 *   4. Clarify-mode — for needs_clarification items; chips + free-text fallback
 *
 * Plus an evidence / provenance block and a manual "Save as food" action (FTY-052/053).
 *
 * The sheet is standalone-presentable: it accepts an item and a session and wires
 * itself to the server. All API calls are injectable for testing.
 *
 * Privacy: food values, the user's phrase, and clarification answers are never
 * logged here. Errors carry only HTTP status + a stable action label.
 */

import {
  useCallback,
  useRef,
  useState,
} from "react";
import {
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type AccessibilityRole,
} from "react-native";

import {
  listSourceCandidates as listSourceCandidatesApi,
  reResolveItem as reResolveItemApi,
  type SourceCandidate,
  CorrectionsApiError,
} from "@/api/corrections";
import {
  editDerivedItem as editDerivedItemApi,
  type DerivedFoodItemDTO,
  type DerivedItem,
  DerivedItemApiError,
} from "@/api/derivedItems";
import {
  saveFood as saveFoodApi,
  type NutritionSnapshot,
} from "@/api/savedFoods";
import { Skeleton } from "@/components/ui/Skeleton";
import { AppIcon } from "@/components/ui/AppIcon";
import {
  provenancePresentation,
  type ProvenancePresentation,
} from "@/components/ui/ProvenanceIcon";
import type { ApiSession } from "@/state/session";
import { formatValue } from "@/state/derivedItems";
import { useTheme, spacing, typeScale, radius } from "@/theme";

/** Clarification data for an item in the needs_clarification state. */
export interface ClarificationData {
  /**
   * Fatty's specific question (e.g. "What kind of milk?"), or `null` while the
   * clarification read is loading or when the event has no persisted question.
   * Clarify-mode falls back to the generic prompt + free-text when it is `null`.
   */
  readonly question: string | null;
  /** Quick-pick answer options (tappable chips). Empty for v1 (FTY-152). */
  readonly options: readonly string[];
}

type SheetMode = "normal" | "change-match" | "override" | "clarify";
type SaveFoodStatus = "idle" | "saving" | "saved" | "error";

/** Props shared by every sheet, regardless of clarify-mode. */
export interface CorrectionSheetBaseProps {
  item: DerivedItem;
  visible: boolean;
  onClose: () => void;
  session: ApiSession;
  onItemChange?: (item: DerivedItem) => void;
  /** The original typed phrase from the log event — shown quoted in evidence block. */
  logPhrase?: string;
  /** Injectable for tests (FTY-051 PATCH). */
  editItem?: typeof editDerivedItemApi;
  /** Injectable for tests (FTY-093 list candidates). */
  listCandidates?: typeof listSourceCandidatesApi;
  /** Injectable for tests (FTY-093 re-resolve). */
  reResolve?: typeof reResolveItemApi;
  /** Injectable for tests (FTY-052/053 save-as-food). */
  saveFood?: typeof saveFoodApi;
}

/**
 * Clarify-mode is a discriminated branch: a `needsClarification` sheet *requires*
 * `clarificationData` (its `question` may be `null` while the read loads), so the
 * "Add a detail" flow can never type-check without wiring the question read. A
 * normal sheet forbids the clarify-only props.
 */
type CorrectionSheetClarifyProps =
  | {
      needsClarification: true;
      clarificationData: ClarificationData;
      /**
       * Called when the user resolves a clarification. The answer is the selected
       * chip text or the free-text the user typed. With no first-class resolve
       * endpoint yet (FTY-152), the parent wires this to the re-submit path.
       */
      onClarificationResolved?: (answer: string) => void;
    }
  | {
      needsClarification?: false;
      clarificationData?: never;
      onClarificationResolved?: never;
    };

export type CorrectionSheetProps = CorrectionSheetBaseProps &
  CorrectionSheetClarifyProps;

/**
 * Debounce for the Change-match search field. Each keystroke would otherwise
 * trigger a USDA FDC name-search fan-out server-side; waiting for a typing pause
 * keeps provider egress bounded (see evidence-retrieval.md `FATTY_FDC_MAX_RESULTS`).
 */
const SEARCH_DEBOUNCE_MS = 300;

/** Map a correction API error to a plain, nonjudgmental message. */
function messageForError(error: unknown, action: string): string {
  if (error instanceof CorrectionsApiError || error instanceof DerivedItemApiError) {
    return (error as { message: string }).message;
  }
  return `We couldn't ${action}. Check your connection and try again.`;
}

// ─── Amount stepper helpers ────────────────────────────────────────────────────

/** Format a numeric amount for display, omitting decimals when integral. */
function formatAmount(amount: number | null): string {
  if (amount === null) return "—";
  return formatValue(amount);
}

/**
 * The correction sheet. Call with `visible={true}` to present it over the
 * current screen; `onClose` is called when the user dismisses it.
 *
 * Height: the sheet uses a medium `maxHeight` by default and switches to a large
 * `maxHeight` when the Change-match search or the advanced override panel opens;
 * it stays medium for the quick-fix path (amount / save). This approximates
 * sheet detents with a plain `Modal`; it is not a draggable native sheet.
 */
export function CorrectionSheet({
  item: initialItem,
  visible,
  onClose,
  session,
  onItemChange,
  logPhrase,
  needsClarification = false,
  clarificationData,
  onClarificationResolved,
  editItem = editDerivedItemApi,
  listCandidates = listSourceCandidatesApi,
  reResolve = reResolveItemApi,
  saveFood = saveFoodApi,
}: CorrectionSheetProps) {
  const { colors } = useTheme();
  const [item, setItem] = useState<DerivedItem>(initialItem);

  // Resync local item when prop changes (parent may push a confirmed edit).
  const [syncedItem, setSyncedItem] = useState<DerivedItem>(initialItem);
  if (initialItem !== syncedItem) {
    setSyncedItem(initialItem);
    setItem(initialItem);
  }

  // Sheet opens in clarify-mode when needs_clarification, otherwise normal.
  const initialMode: SheetMode = needsClarification ? "clarify" : "normal";
  const [mode, setMode] = useState<SheetMode>(initialMode);

  // Sync mode when needsClarification prop changes or sheet re-opens.
  const [syncedNeedsClarification, setSyncedNeedsClarification] = useState(needsClarification);
  if (needsClarification !== syncedNeedsClarification) {
    setSyncedNeedsClarification(needsClarification);
    setMode(needsClarification ? "clarify" : "normal");
  }

  // Large detent when Change-match or override is open.
  const expanded = mode === "change-match" || mode === "override";

  // Clarify-mode pins a minimum height so the question + free-text input + "Done"
  // always render at a usable height. The body is a flex:1 ScrollView, which
  // collapses to a near-zero strip when the sheet hugs its (short) clarify
  // content — the live RC bug this story fixes. A floor gives it room in both
  // states: question present, and question absent/loading.
  const clarifying = mode === "clarify";

  // ─── Amount stepper state ───────────────────────────────────────────────────
  const [amountPending, setAmountPending] = useState(false);
  const [amountError, setAmountError] = useState<string | null>(null);

  // ─── Change-match state ─────────────────────────────────────────────────────
  const [candidates, setCandidates] = useState<readonly SourceCandidate[]>([]);
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
  const [overrideDraft, setOverrideDraft] = useState("");
  const [overrideSaving, setOverrideSaving] = useState(false);
  const [overrideError, setOverrideError] = useState<string | null>(null);

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
      setMode(needsClarification ? "clarify" : "normal");
      setAmountError(null);
      setCandidates([]);
      setCandidatesError(null);
      setMatchQuery("");
      setReResolveError(null);
      setOverrideDraft("");
      setOverrideError(null);
      setClarifyText("");
      setSaveFoodStatus("idle");
      setSaveFoodError(null);
    }
  }

  // ─── Amount stepper ─────────────────────────────────────────────────────────

  const currentAmount =
    item.item_type === "food" ? (item as DerivedFoodItemDTO).amount : null;
  const unit =
    item.item_type === "food" ? (item as DerivedFoodItemDTO).unit : null;

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
      } catch (err) {
        setItem(prior);
        setAmountError(messageForError(err, "adjust the amount"));
      } finally {
        setAmountPending(false);
      }
    },
    [item, editItem, session, onItemChange],
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
        setCandidates(results);
      } catch (err) {
        if (seq !== searchSeq.current) return; // superseded by a newer query
        setCandidatesError(messageForError(err, "load alternatives"));
        setCandidates([]);
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
    async (candidate: SourceCandidate) => {
      if (item.item_type !== "food") return;
      const food = item as DerivedFoodItemDTO;
      cancelPendingSearch();
      setReResolving(true);
      setReResolveError(null);
      try {
        const updated = await reResolve(session, food.id, candidate.source_ref);
        setItem(updated);
        onItemChange?.(updated);
        setMode("normal");
        setMatchQuery("");
        setCandidates([]);
      } catch (err) {
        setReResolveError(messageForError(err, "apply that match"));
      } finally {
        setReResolving(false);
      }
    },
    [item, reResolve, session, onItemChange, cancelPendingSearch],
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
    } catch (err) {
      setItem(prior);
      setOverrideError(messageForError(err, "save that override"));
    } finally {
      setOverrideSaving(false);
    }
  }, [item, editItem, session, onItemChange, overrideField, overrideDraft]);

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

  // ─── Derived UI values ───────────────────────────────────────────────────────

  const food = item.item_type === "food" ? (item as DerivedFoodItemDTO) : null;
  const source = food?.source ?? null;
  const isEdited = item.is_edited ?? false;
  const isRoughEstimate =
    !isEdited && source?.source_type === "model_prior";

  const provenancePres = provenancePresentation(source, isEdited);
  const kcal =
    item.item_type === "food" ? food?.calories ?? null : null;
  const canSaveFood =
    food !== null && food.calories !== null && !!logPhrase;

  const sheetBg = colors.surfaceRaised;

  // ─── Render ───────────────────────────────────────────────────────────────────

  return (
    <Modal
      visible={visible}
      transparent
      animationType="slide"
      presentationStyle="overFullScreen"
      onRequestClose={onClose}
      accessibilityViewIsModal
    >
      <View style={styles.overlay}>
        {/* Backdrop — tapping closes the sheet */}
        <Pressable
          style={StyleSheet.absoluteFill}
          onPress={onClose}
          accessibilityLabel="Close sheet"
          accessibilityRole={"button" as AccessibilityRole}
        />

        {/* Sheet */}
        <View
          style={[
            styles.sheet,
            { backgroundColor: sheetBg },
            expanded ? styles.sheetLarge : styles.sheetMedium,
            clarifying ? styles.sheetClarify : null,
          ]}
        >
          {/* Decorative grabber (non-draggable; hidden from assistive tech) */}
          <View
            style={styles.handleContainer}
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
          >
            <View style={[styles.handle, { backgroundColor: colors.textMuted }]} />
          </View>

          {/* Header */}
          <View style={styles.header}>
            <Text style={[styles.title, { color: colors.text }]} numberOfLines={1}>
              {item.name}
            </Text>
            <Pressable
              onPress={onClose}
              accessibilityLabel="Close"
              accessibilityRole="button"
              style={styles.closeButton}
            >
              <Text style={[styles.closeLabel, { color: colors.accent }]}>Done</Text>
            </Pressable>
          </View>

          <ScrollView
            style={styles.scrollContent}
            contentContainerStyle={styles.scrollInner}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
            {mode === "clarify" ? (
              <ClarifyMode
                clarificationData={clarificationData}
                clarifyText={clarifyText}
                onChangeClarifyText={setClarifyText}
                onSubmitAnswer={handleClarifyAnswer}
                submitting={clarifySubmitting}
                colors={colors}
              />
            ) : (
              <>
                {/* Evidence / provenance block */}
                <ProvenanceBlock
                  source={source}
                  isEdited={isEdited}
                  provenancePres={provenancePres}
                  isRoughEstimate={isRoughEstimate}
                  logPhrase={logPhrase}
                  onMakeExact={openChangeMatch}
                  colors={colors}
                />

                {/* Separator */}
                <View style={[styles.separator, { backgroundColor: colors.separator }]} />

                {/* Amount stepper (food only) */}
                {food !== null ? (
                  <AmountStepper
                    amount={currentAmount}
                    unit={unit}
                    quantityText={food.quantity_text}
                    kcal={kcal}
                    protein={food.protein_g}
                    carbs={food.carbs_g}
                    fat={food.fat_g}
                    pending={amountPending}
                    error={amountError}
                    onStepDown={() => void handleAmountStep(-0.25)}
                    onStepUp={() => void handleAmountStep(0.25)}
                    colors={colors}
                  />
                ) : null}

                {/* Change match lever */}
                {food !== null && mode !== "change-match" ? (
                  <>
                    <View style={[styles.separator, { backgroundColor: colors.separator }]} />
                    <Pressable
                      onPress={openChangeMatch}
                      style={styles.leverButton}
                      accessibilityRole="button"
                      accessibilityLabel="Change match"
                      accessibilityHint="Find a different food source for this entry"
                    >
                      <Text style={[styles.leverLabel, { color: colors.accent }]}>
                        Change match
                      </Text>
                      <Text style={[styles.leverChevron, { color: colors.textMuted }]}>›</Text>
                    </Pressable>
                  </>
                ) : null}

                {/* Change-match panel */}
                {mode === "change-match" ? (
                  <ChangMatchPanel
                    query={matchQuery}
                    onQueryChange={handleCandidateSearch}
                    candidates={candidates}
                    loading={candidatesLoading}
                    error={candidatesError}
                    reResolving={reResolving}
                    reResolveError={reResolveError}
                    onPickCandidate={(c) => void handlePickCandidate(c)}
                    onCancel={() => {
                      cancelPendingSearch();
                      setMode("normal");
                      setMatchQuery("");
                      setCandidates([]);
                      setCandidatesError(null);
                    }}
                    colors={colors}
                  />
                ) : null}

                {/* Advanced override lever */}
                {food !== null && mode !== "override" && mode !== "change-match" ? (
                  <>
                    <View style={[styles.separator, { backgroundColor: colors.separator }]} />
                    <AdvancedLeverRow
                      food={food}
                      onOpenOverride={openOverride}
                      colors={colors}
                    />
                  </>
                ) : null}

                {/* Override panel */}
                {mode === "override" ? (
                  <OverridePanel
                    field={overrideField}
                    draft={overrideDraft}
                    saving={overrideSaving}
                    error={overrideError}
                    onChangeDraft={setOverrideDraft}
                    onSubmit={() => void submitOverride()}
                    onCancel={() => {
                      setMode("normal");
                      setOverrideDraft("");
                      setOverrideError(null);
                    }}
                    colors={colors}
                  />
                ) : null}

                {/* Save as food */}
                {canSaveFood && mode === "normal" ? (
                  <>
                    <View style={[styles.separator, { backgroundColor: colors.separator }]} />
                    <SaveFoodRow
                      status={saveFoodStatus}
                      error={saveFoodError}
                      onSave={() => void handleSaveFood()}
                      colors={colors}
                    />
                  </>
                ) : null}
              </>
            )}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

// ─── Sub-components ────────────────────────────────────────────────────────────

function ProvenanceBlock({
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
  colors: ReturnType<typeof useTheme>["colors"];
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
          <Text style={[styles.makeExactLabel, { color: colors.accent }]}>
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

function AmountStepper({
  amount,
  unit,
  quantityText,
  kcal,
  protein,
  carbs,
  fat,
  pending,
  error,
  onStepDown,
  onStepUp,
  colors,
}: {
  amount: number | null;
  unit: string | null;
  quantityText: string;
  kcal: number | null;
  protein: number | null;
  carbs: number | null;
  fat: number | null;
  pending: boolean;
  error: string | null;
  onStepDown: () => void;
  onStepUp: () => void;
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  const amountDisplay = amount !== null
    ? `${formatAmount(amount)}${unit ? ` ${unit}` : ""}`
    : quantityText;

  return (
    <View style={styles.stepperSection}>
      <Text style={[styles.sectionLabel, { color: colors.textSecondary }]}>
        Portion
      </Text>
      <View style={styles.stepperRow}>
        <Pressable
          onPress={onStepDown}
          style={[styles.stepperButton, { backgroundColor: colors.controlBackground }]}
          accessibilityLabel="Decrease amount"
          accessibilityRole="button"
          disabled={pending || amount === null || amount <= 0.25}
          accessibilityState={{ disabled: pending || amount === null || amount <= 0.25 }}
        >
          <Text style={[styles.stepperButtonLabel, { color: colors.text }]}>−</Text>
        </Pressable>
        <Text style={[styles.stepperValue, { color: colors.text }]} accessibilityLabel={`Amount: ${amountDisplay}`}>
          {amountDisplay}
        </Text>
        <Pressable
          onPress={onStepUp}
          style={[styles.stepperButton, { backgroundColor: colors.controlBackground }]}
          accessibilityLabel="Increase amount"
          accessibilityRole="button"
          disabled={pending}
          accessibilityState={{ disabled: pending }}
        >
          <Text style={[styles.stepperButtonLabel, { color: colors.text }]}>+</Text>
        </Pressable>
      </View>

      {/* Recomputed nutrition — server values only, never client math */}
      <View style={styles.nutritionRow}>
        {pending ? (
          <>
            <Skeleton width={60} height={18} borderRadius={4} />
            <Skeleton width={48} height={14} borderRadius={4} />
            <Skeleton width={48} height={14} borderRadius={4} />
            <Skeleton width={48} height={14} borderRadius={4} />
          </>
        ) : (
          <>
            <Text
              style={[styles.kcalValue, { color: colors.text }]}
              accessibilityLabel={`${kcal !== null ? Math.round(kcal) : "—"} calories`}
            >
              {kcal !== null ? `${Math.round(kcal)} kcal` : "—"}
            </Text>
            <Text style={[styles.macroChip, { color: colors.textSecondary }]} accessibilityLabel={`${formatAmount(protein)} g protein`}>
              P {formatAmount(protein)}g
            </Text>
            <Text style={[styles.macroChip, { color: colors.textSecondary }]} accessibilityLabel={`${formatAmount(carbs)} g carbs`}>
              C {formatAmount(carbs)}g
            </Text>
            <Text style={[styles.macroChip, { color: colors.textSecondary }]} accessibilityLabel={`${formatAmount(fat)} g fat`}>
              F {formatAmount(fat)}g
            </Text>
          </>
        )}
      </View>

      {error ? (
        <Text style={[styles.errorText, { color: colors.coral }]} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
    </View>
  );
}

function ChangMatchPanel({
  query,
  onQueryChange,
  candidates,
  loading,
  error,
  reResolving,
  reResolveError,
  onPickCandidate,
  onCancel,
  colors,
}: {
  query: string;
  onQueryChange: (q: string) => void;
  candidates: readonly SourceCandidate[];
  loading: boolean;
  error: string | null;
  reResolving: boolean;
  reResolveError: string | null;
  onPickCandidate: (c: SourceCandidate) => void;
  onCancel: () => void;
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  return (
    <View style={styles.changMatchPanel}>
      <View style={styles.changMatchHeader}>
        <Text style={[styles.changMatchTitle, { color: colors.text }]}>
          Change match
        </Text>
        <Pressable
          onPress={onCancel}
          accessibilityLabel="Cancel change match"
          accessibilityRole="button"
          style={styles.cancelButton}
        >
          <Text style={[styles.cancelLabel, { color: colors.accent }]}>Cancel</Text>
        </Pressable>
      </View>

      {/* Search field */}
      <TextInput
        accessibilityLabel="Search for a food"
        placeholder="Search for a different food…"
        placeholderTextColor={colors.textMuted}
        value={query}
        onChangeText={onQueryChange}
        style={[
          styles.searchInput,
          {
            backgroundColor: colors.controlBackground,
            color: colors.text,
          },
        ]}
        returnKeyType="search"
        autoCorrect={false}
        clearButtonMode="while-editing"
      />

      {reResolveError ? (
        <Text style={[styles.errorText, { color: colors.coral }]} accessibilityRole="alert">
          {reResolveError}
        </Text>
      ) : null}

      {loading ? (
        <View style={styles.candidateSkeletonList}>
          <Skeleton width="100%" height={44} borderRadius={radius.md} />
          <Skeleton width="100%" height={44} borderRadius={radius.md} />
          <Skeleton width="100%" height={44} borderRadius={radius.md} />
        </View>
      ) : error ? (
        <Text style={[styles.errorText, { color: colors.coral }]} accessibilityRole="alert">
          {error}
        </Text>
      ) : candidates.length === 0 ? (
        <Text style={[styles.emptyLabel, { color: colors.textMuted }]}>
          {query.trim() ? "No matches found. Try a different search." : "No alternatives available."}
        </Text>
      ) : (
        <View style={styles.candidateList} accessibilityRole="list">
          {candidates.map((candidate) => (
            <Pressable
              key={candidate.source_ref}
              onPress={() => onPickCandidate(candidate)}
              style={({ pressed }) => [
                styles.candidateRow,
                { borderBottomColor: colors.separator },
                pressed && { opacity: 0.7 },
              ]}
              accessibilityRole="button"
              accessibilityLabel={`Select ${candidate.name}, ${Math.round(candidate.calories)} kcal per 100g`}
              disabled={reResolving}
              accessibilityState={{ disabled: reResolving }}
            >
              <View style={styles.candidateInfo}>
                <Text style={[styles.candidateName, { color: colors.text }]} numberOfLines={1}>
                  {candidate.name}
                </Text>
                <Text style={[styles.candidateMeta, { color: colors.textMuted }]}>
                  {Math.round(candidate.calories)} kcal / 100g
                </Text>
              </View>
              {reResolving ? null : (
                <Text style={[styles.candidateChevron, { color: colors.textMuted }]}>›</Text>
              )}
            </Pressable>
          ))}
        </View>
      )}
    </View>
  );
}

/** Editable fields for the advanced override panel. */
const OVERRIDE_FIELDS = [
  { field: "calories", label: "Calories", unit: "kcal", key: "calories" as const },
  { field: "protein_g", label: "Protein", unit: "g", key: "protein_g" as const },
  { field: "carbs_g", label: "Carbs", unit: "g", key: "carbs_g" as const },
  { field: "fat_g", label: "Fat", unit: "g", key: "fat_g" as const },
] as const;

function AdvancedLeverRow({
  food,
  onOpenOverride,
  colors,
}: {
  food: DerivedFoodItemDTO;
  onOpenOverride: (field: string, value: number | null) => void;
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  return (
    <View style={styles.advancedSection}>
      <Text style={[styles.sectionLabel, { color: colors.textSecondary }]}>
        Advanced — edit values directly
      </Text>
      {OVERRIDE_FIELDS.map(({ field, label, unit, key }) => {
        const value = food[key];
        return (
          <Pressable
            key={field}
            onPress={() => onOpenOverride(field, value)}
            style={styles.overrideFieldRow}
            accessibilityRole="button"
            accessibilityLabel={`Override ${label}${value !== null ? `, currently ${formatValue(value)} ${unit}` : ""}`}
          >
            <Text style={[styles.overrideFieldLabel, { color: colors.textSecondary }]}>
              {label}
            </Text>
            <Text style={[styles.overrideFieldValue, { color: colors.text }]}>
              {value !== null ? `${formatValue(value)} ${unit}` : "—"}
            </Text>
            <Text style={[styles.leverChevron, { color: colors.textMuted }]}>›</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const FIELD_LABELS: Record<string, { label: string; unit: string }> = {
  calories: { label: "Calories", unit: "kcal" },
  protein_g: { label: "Protein", unit: "g" },
  carbs_g: { label: "Carbs", unit: "g" },
  fat_g: { label: "Fat", unit: "g" },
};

function OverridePanel({
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
  colors: ReturnType<typeof useTheme>["colors"];
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

function ClarifyMode({
  clarificationData,
  clarifyText,
  onChangeClarifyText,
  onSubmitAnswer,
  submitting,
  colors,
}: {
  clarificationData?: ClarificationData;
  clarifyText: string;
  onChangeClarifyText: (v: string) => void;
  onSubmitAnswer: (answer: string) => void;
  submitting: boolean;
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  return (
    <View style={styles.clarifySection}>
      {/* Question — testID targets this element in Maestro (FTY-162 clarify flow). */}
      <Text
        testID="clarify-question"
        style={[styles.clarifyQuestion, { color: colors.text }]}
      >
        {clarificationData?.question ?? "We need a detail to count this entry."}
      </Text>

      {/* Quick-pick chips */}
      {clarificationData && clarificationData.options.length > 0 ? (
        <View style={styles.chipRow} accessibilityRole="radiogroup">
          {clarificationData.options.map((option) => (
            <Pressable
              key={option}
              onPress={() => onSubmitAnswer(option)}
              style={[styles.chip, { backgroundColor: colors.controlBackground }]}
              accessibilityRole="radio"
              accessibilityLabel={option}
              disabled={submitting}
              accessibilityState={{ disabled: submitting }}
            >
              <Text style={[styles.chipLabel, { color: colors.text }]}>{option}</Text>
            </Pressable>
          ))}
        </View>
      ) : null}

      {/* Free-text fallback */}
      <Text style={[styles.clarifyOrLabel, { color: colors.textMuted }]}>
        {clarificationData && clarificationData.options.length > 0
          ? "Or type your own:"
          : "Type your answer:"}
      </Text>
      <View style={styles.clarifyInputRow}>
        <TextInput
          accessibilityLabel="Your answer"
          placeholder="Type your answer…"
          placeholderTextColor={colors.textMuted}
          value={clarifyText}
          onChangeText={onChangeClarifyText}
          style={[
            styles.clarifyInput,
            {
              backgroundColor: colors.controlBackground,
              color: colors.text,
              flex: 1,
            },
          ]}
          editable={!submitting}
          returnKeyType="done"
          onSubmitEditing={() => {
            if (clarifyText.trim()) {
              onSubmitAnswer(clarifyText);
            }
          }}
        />
        <Pressable
          onPress={() => {
            if (clarifyText.trim()) {
              onSubmitAnswer(clarifyText);
            }
          }}
          style={[
            styles.clarifySubmitBtn,
            { backgroundColor: clarifyText.trim() ? colors.accent : colors.controlBackground },
          ]}
          accessibilityRole="button"
          accessibilityLabel="Submit answer"
          disabled={submitting || !clarifyText.trim()}
          accessibilityState={{ disabled: submitting || !clarifyText.trim() }}
        >
          <Text
            style={[
              styles.clarifySubmitLabel,
              { color: clarifyText.trim() ? colors.accentForeground : colors.textMuted },
            ]}
          >
            {submitting ? "…" : "Done"}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

function SaveFoodRow({
  status,
  error,
  onSave,
  colors,
}: {
  status: SaveFoodStatus;
  error: string | null;
  onSave: () => void;
  colors: ReturnType<typeof useTheme>["colors"];
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

// ─── Styles ────────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: "flex-end",
    backgroundColor: "rgba(0,0,0,0.35)",
  },
  sheet: {
    borderTopLeftRadius: radius.xl,
    borderTopRightRadius: radius.xl,
    overflow: "hidden",
  },
  sheetMedium: {
    maxHeight: "55%",
  },
  sheetLarge: {
    maxHeight: "90%",
  },
  // Clarify-mode height floor: the body's flex:1 ScrollView collapses to a
  // near-zero strip when the sheet hugs short clarify content, so pin a minimum
  // height that keeps the question + free-text input + "Done" usable. Stays under
  // sheetMedium's 55% max, so the sheet never grows past the medium detent.
  sheetClarify: {
    minHeight: "42%",
  },
  handleContainer: {
    alignItems: "center",
    paddingTop: spacing.md,
    paddingBottom: spacing.xs,
  },
  handle: {
    width: 36,
    height: 4,
    borderRadius: radius.full,
    opacity: 0.35,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.base,
    paddingBottom: spacing.sm,
    gap: spacing.sm,
  },
  title: {
    flex: 1,
    fontSize: typeScale.headline,
    fontWeight: "600",
  },
  closeButton: {
    minWidth: 44,
    minHeight: 44,
    alignItems: "flex-end",
    justifyContent: "center",
  },
  closeLabel: {
    fontSize: typeScale.callout,
    fontWeight: "600",
  },
  scrollContent: {
    flex: 1,
  },
  scrollInner: {
    paddingBottom: spacing.xxxl,
  },
  separator: {
    height: StyleSheet.hairlineWidth,
    marginHorizontal: spacing.base,
  },

  // Provenance block
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

  // Amount stepper
  stepperSection: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    gap: spacing.sm,
  },
  sectionLabel: {
    fontSize: typeScale.footnote,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.5,
  },
  stepperRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.md,
  },
  stepperButton: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  stepperButtonLabel: {
    fontSize: 22,
    fontWeight: "300",
  },
  stepperValue: {
    flex: 1,
    textAlign: "center",
    fontSize: typeScale.title3,
    fontWeight: "600",
    fontVariant: ["tabular-nums"],
  },
  nutritionRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    flexWrap: "wrap",
  },
  kcalValue: {
    fontSize: typeScale.callout,
    fontWeight: "700",
    fontVariant: ["tabular-nums"],
  },
  macroChip: {
    fontSize: typeScale.footnote,
    fontVariant: ["tabular-nums"],
  },

  // Change match lever
  leverButton: {
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    minHeight: 44,
    gap: spacing.sm,
  },
  leverLabel: {
    flex: 1,
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  leverChevron: {
    fontSize: 20,
    fontWeight: "300",
  },

  // Change-match panel
  changMatchPanel: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    gap: spacing.sm,
  },
  changMatchHeader: {
    flexDirection: "row",
    alignItems: "center",
  },
  changMatchTitle: {
    flex: 1,
    fontSize: typeScale.headline,
    fontWeight: "600",
  },
  cancelButton: {
    minHeight: 44,
    minWidth: 44,
    alignItems: "flex-end",
    justifyContent: "center",
  },
  cancelLabel: {
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  searchInput: {
    height: 44,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    fontSize: typeScale.callout,
  },
  candidateSkeletonList: {
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  candidateList: {
    marginTop: spacing.xs,
  },
  candidateRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: spacing.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    minHeight: 56,
    gap: spacing.sm,
  },
  candidateInfo: {
    flex: 1,
    gap: 2,
  },
  candidateName: {
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  candidateMeta: {
    fontSize: typeScale.footnote,
    fontVariant: ["tabular-nums"],
  },
  candidateChevron: {
    fontSize: 20,
  },
  emptyLabel: {
    fontSize: typeScale.subhead,
    textAlign: "center",
    paddingVertical: spacing.xl,
  },

  // Advanced / override
  advancedSection: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    gap: spacing.xs,
  },
  overrideFieldRow: {
    flexDirection: "row",
    alignItems: "center",
    paddingVertical: spacing.md,
    minHeight: 44,
    gap: spacing.sm,
  },
  overrideFieldLabel: {
    width: 72,
    fontSize: typeScale.callout,
  },
  overrideFieldValue: {
    flex: 1,
    fontSize: typeScale.callout,
    fontVariant: ["tabular-nums"],
  },
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

  // Clarify mode
  clarifySection: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.lg,
    gap: spacing.md,
  },
  clarifyQuestion: {
    fontSize: typeScale.headline,
    fontWeight: "600",
  },
  chipRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: spacing.sm,
  },
  chip: {
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    borderRadius: radius.full,
    minHeight: 44,
    justifyContent: "center",
  },
  chipLabel: {
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  clarifyOrLabel: {
    fontSize: typeScale.footnote,
  },
  clarifyInputRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
  },
  clarifyInput: {
    height: 44,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    fontSize: typeScale.callout,
  },
  clarifySubmitBtn: {
    width: 60,
    height: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  clarifySubmitLabel: {
    fontSize: typeScale.callout,
    fontWeight: "600",
  },

  // Save as food
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

  // Shared
  errorText: {
    fontSize: typeScale.footnote,
  },
});
