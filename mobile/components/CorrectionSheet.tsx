/**
 * FTY-100: Universal detail / correction sheet.
 *
 * A sheet that opens from any timeline item and provides four ordered levers for
 * correction:
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
 *
 * FTY-204: this file is now a thin mode-switching shell. The four levers' state
 * and async handlers live in `correction/useCorrectionSheet`; each mode panel and
 * row primitive is its own focused module under `components/correction/`.
 */

import {
  Animated,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from "react-native";

import {
  listSourceCandidates as listSourceCandidatesApi,
  reResolveItem as reResolveItemApi,
} from "@/api/corrections";
import {
  editDerivedItem as editDerivedItemApi,
  type DerivedFoodItemDTO,
  type DerivedItem,
} from "@/api/derivedItems";
import { saveFood as saveFoodApi } from "@/api/savedFoods";
import { ClarifyMode, type ClarificationData } from "@/components/ClarifyMode";
import { AdvancedLeverRow } from "@/components/correction/AdvancedLeverRow";
import { AmountStepper } from "@/components/correction/AmountStepper";
import { ChangeMatchPanel } from "@/components/correction/ChangeMatchPanel";
import { OverridePanel } from "@/components/correction/OverridePanel";
import { ProvenanceBlock } from "@/components/correction/ProvenanceBlock";
import { SaveFoodRow } from "@/components/correction/SaveFoodRow";
import {
  useCorrectionSheet,
  type SheetMode,
} from "@/components/correction/useCorrectionSheet";
import { DisplayText } from "@/components/ui/DisplayText";
import { NativeSheet } from "@/components/ui/NativeSheet";
import { provenancePresentation } from "@/components/ui/ProvenanceIcon";
import type { ApiSession } from "@/state/session";
import { useTheme, spacing, typeScale, radius } from "@/theme";

export type { ClarificationData } from "@/components/ClarifyMode";

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
  /**
   * E2E-only: opens the sheet directly into this mode (FTY-263 visual-review
   * seam). Never set by a real caller — Today's sheet host only supplies it
   * from the visual-review seam, which is itself gated behind `isE2EMode()`.
   */
  e2eInitialMode?: SheetMode;
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
 * The correction sheet. Call with `visible={true}` to present it over the
 * current screen; `onClose` is called when the user dismisses it.
 *
 * Presentation: a real native sheet (`NativeSheet`) with medium → large detents.
 * It opens at the medium detent — timeline visible behind, undimmed — for the
 * quick-fix path (amount / save), and expands to the large detent when the
 * Change-match search or advanced override panel opens (there the detents narrow
 * to large-only so UIKit animates the growth, and the content behind dims to
 * focus the search). The grabber, swipe-to-dismiss, and Reduce Motion come from
 * the native presentation controller.
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
  e2eInitialMode,
}: CorrectionSheetProps) {
  const { colors } = useTheme();

  const sheet = useCorrectionSheet({
    initialItem,
    visible,
    session,
    onItemChange,
    logPhrase,
    needsClarification,
    onClarificationResolved,
    editItem,
    listCandidates,
    reResolve,
    saveFood,
    initialMode: e2eInitialMode,
  });
  const { item, mode, expanded } = sheet;

  // ─── Derived display values ────────────────────────────────────────────────
  const food = item.item_type === "food" ? (item as DerivedFoodItemDTO) : null;
  const source = food?.source ?? null;
  const isEdited = item.is_edited ?? false;
  const isRoughEstimate = !isEdited && source?.source_type === "model_prior";
  const provenancePres = provenancePresentation(source, isEdited);
  const currentAmount = food?.amount ?? null;
  const unit = food?.unit ?? null;
  const kcal = food?.calories ?? null;
  const canSaveFood = food !== null && food.calories !== null && !!logPhrase;

  return (
    <NativeSheet
      visible={visible}
      onClose={onClose}
      // Medium → large. When a panel wants the room, narrow to large-only so
      // UIKit animates the growth (see `expanded`).
      detents={expanded ? [1.0] : [0.5, 1.0]}
      // Medium stays undimmed → timeline visible behind the quick fix; the
      // large-only expanded state dims to focus the search/override.
      largestUndimmedDetentIndex={expanded ? "none" : 0}
      initialDetentIndex={0}
      grabberVisible
      cornerRadius={radius.xl}
      backgroundColor={colors.surfaceRaised}
      accessibilityLabel={`${item.name} details`}
    >
      {/* Beat 2 — a brief confirmation pulse on a successful correction. The
          native sheet owns its presentation motion; this only animates the
          content on save. `usePulse` degrades to a fade under Reduce Motion. */}
      <Animated.View
        style={[styles.sheetBody, { opacity: sheet.opacity, transform: [{ scale: sheet.scale }] }]}
      >
        {/* Header */}
        <View style={styles.header}>
          <DisplayText scale="headline" style={styles.title} numberOfLines={1}>
            {item.name}
          </DisplayText>
          <Pressable
            onPress={onClose}
            accessibilityLabel="Close"
            accessibilityRole="button"
            style={styles.closeButton}
          >
            <Text style={[styles.closeLabel, { color: colors.accentText }]}>Done</Text>
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
              clarifyText={sheet.clarifyText}
              onChangeClarifyText={sheet.setClarifyText}
              onSubmitAnswer={sheet.handleClarifyAnswer}
              submitting={sheet.clarifySubmitting}
              colors={colors}
              logPhrase={logPhrase}
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
                onMakeExact={sheet.openChangeMatch}
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
                  pending={sheet.amountPending}
                  error={sheet.amountError}
                  onStepDown={() => void sheet.handleAmountStep(-0.25)}
                  onStepUp={() => void sheet.handleAmountStep(0.25)}
                  colors={colors}
                />
              ) : null}

              {/* Change match lever */}
              {food !== null && mode !== "change-match" ? (
                <>
                  <View style={[styles.separator, { backgroundColor: colors.separator }]} />
                  <Pressable
                    onPress={sheet.openChangeMatch}
                    style={styles.leverButton}
                    accessibilityRole="button"
                    accessibilityLabel="Change match"
                    accessibilityHint="Find a different food source for this entry"
                  >
                    <Text style={[styles.leverLabel, { color: colors.accentText }]}>
                      Change match
                    </Text>
                    <Text style={[styles.leverChevron, { color: colors.textMuted }]}>›</Text>
                  </Pressable>
                </>
              ) : null}

              {/* Change-match panel */}
              {mode === "change-match" ? (
                <ChangeMatchPanel
                  query={sheet.matchQuery}
                  onQueryChange={sheet.handleCandidateSearch}
                  candidates={sheet.candidates}
                  loading={sheet.candidatesLoading}
                  error={sheet.candidatesError}
                  reResolving={sheet.reResolving}
                  reResolveError={sheet.reResolveError}
                  onPickCandidate={(c) => void sheet.handlePickCandidate(c)}
                  onCancel={sheet.cancelChangeMatch}
                  colors={colors}
                />
              ) : null}

              {/* Advanced override lever */}
              {food !== null && mode !== "override" && mode !== "change-match" ? (
                <>
                  <View style={[styles.separator, { backgroundColor: colors.separator }]} />
                  <AdvancedLeverRow
                    food={food}
                    onOpenOverride={sheet.openOverride}
                    colors={colors}
                  />
                </>
              ) : null}

              {/* Override panel */}
              {mode === "override" ? (
                <OverridePanel
                  field={sheet.overrideField}
                  draft={sheet.overrideDraft}
                  saving={sheet.overrideSaving}
                  error={sheet.overrideError}
                  onChangeDraft={sheet.setOverrideDraft}
                  onSubmit={() => void sheet.submitOverride()}
                  onCancel={sheet.cancelOverride}
                  colors={colors}
                />
              ) : null}

              {/* Save as food */}
              {canSaveFood && mode === "normal" ? (
                <>
                  <View style={[styles.separator, { backgroundColor: colors.separator }]} />
                  <SaveFoodRow
                    status={sheet.saveFoodStatus}
                    error={sheet.saveFoodError}
                    onSave={() => void sheet.handleSaveFood()}
                    colors={colors}
                  />
                </>
              ) : null}
            </>
          )}
        </ScrollView>
      </Animated.View>
    </NativeSheet>
  );
}

// ─── Shell styles ──────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  // The native sheet owns the rounded top, grabber, and detent height; the body
  // just fills it. `flex: 1` lets the ScrollView scroll within the current detent.
  sheetBody: {
    flex: 1,
    paddingTop: spacing.sm,
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
    fontSize: typeScale.title3,
    fontWeight: "300",
  },
});
