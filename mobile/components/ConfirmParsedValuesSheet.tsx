/**
 * FTY-197: Confirm-parsed-values sheet.
 *
 * After a legible nutrition-label upload the parse lands as an **uncounted
 * proposal** (a `proposed` derived food item — FTY-196). This sheet shows those
 * parsed values (name/serving, calories, macros) with the "Label scan"
 * provenance and a visible **not-yet-counted** state, and lets the user
 * **confirm** (looks right) or **adjust** the values before the entry counts.
 * It never auto-confirms: the parse does not count until the user acts, and
 * dismissing without confirming leaves the proposal uncounted.
 *
 *   Confirm → commits the parse as-is (FTY-196 confirm, empty body) → resolved.
 *   Adjust  → edit portion / values, then commit the changed fields so the
 *             corrected numbers count (a value override marks the item edited;
 *             an adjusted serving count is a provenance-preserving rescale).
 *
 * "Capture the nutrition label, then confirm the parsed values (looks-right /
 * edit) before it's added" (`docs/design/ux-design.md` §3) — enforcing "never
 * silently trust a fallible parse" (`docs/design-philosophy.md`).
 *
 * Privacy: nutrition values and the parse are never logged here; errors carry
 * only the HTTP status + a stable action label.
 */

import { useCallback, useEffect, useState } from "react";
import {
  AccessibilityInfo,
  Modal,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type AccessibilityRole,
} from "react-native";

import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import {
  confirmLabelProposal as confirmLabelProposalApi,
  LabelProposalApiError,
  type LabelProposalAdjustments,
} from "@/api/labelProposal";
import { AppIcon } from "@/components/ui/AppIcon";
import { provenancePresentation } from "@/components/ui/ProvenanceIcon";
import { ThemedNumber } from "@/components/ui/ThemedNumber";
import type { ApiSession } from "@/state/session";
import { formatValue } from "@/state/derivedItems";
import { useTheme, spacing, typeScale, radius } from "@/theme";

/** Fields the adjust panel can override, in display order. */
const VALUE_FIELDS = [
  { key: "calories", label: "Calories", unit: "kcal" },
  { key: "protein_g", label: "Protein", unit: "g" },
  { key: "carbs_g", label: "Carbs", unit: "g" },
  { key: "fat_g", label: "Fat", unit: "g" },
] as const;

type ValueFieldKey = (typeof VALUE_FIELDS)[number]["key"];

/** Smallest editable serving step, mirroring the correction sheet's stepper. */
const AMOUNT_STEP = 0.25;
const MIN_AMOUNT = 0.25;

export interface ConfirmParsedValuesSheetProps {
  /** The uncounted proposal to confirm/adjust (FTY-196 read shape). */
  item: DerivedFoodItemDTO;
  visible: boolean;
  session: ApiSession;
  /** Called when the user dismisses without confirming — the proposal stays uncounted. */
  onClose: () => void;
  /** Called with the committed, now-counted item after a successful confirm. */
  onConfirmed: (item: DerivedFoodItemDTO) => void;
  /** Injectable confirm action for tests (FTY-196). */
  confirm?: typeof confirmLabelProposalApi;
}

function messageForError(error: unknown): string {
  if (error instanceof LabelProposalApiError) {
    return error.message;
  }
  return "We couldn't add that entry. Check your connection and try again.";
}

/** The parsed serving as a display string (e.g. "1 serving", "2 bars"). */
function servingDisplay(item: DerivedFoodItemDTO): string {
  if (item.amount !== null) {
    return `${formatValue(item.amount)}${item.unit ? ` ${item.unit}` : item.quantity_text ? ` × ${item.quantity_text}` : ""}`;
  }
  return item.quantity_text;
}

/**
 * The confirm-parsed-values sheet. Presented over Today after a legible label
 * upload; `onClose` fires when dismissed without confirming (proposal stays
 * uncounted), `onConfirmed` fires with the committed item once it counts.
 */
export function ConfirmParsedValuesSheet({
  item,
  visible,
  session,
  onClose,
  onConfirmed,
  confirm = confirmLabelProposalApi,
}: ConfirmParsedValuesSheetProps) {
  const { colors } = useTheme();

  // Reduce Motion: start motion-free, enable slide only if the system says off.
  const [reduceMotion, setReduceMotion] = useState<boolean | null>(null);
  useEffect(() => {
    let mounted = true;
    AccessibilityInfo.isReduceMotionEnabled().then(
      (enabled) => {
        if (mounted) setReduceMotion(enabled);
      },
      () => {
        if (mounted) setReduceMotion(true);
      },
    );
    const subscription = AccessibilityInfo.addEventListener(
      "reduceMotionChanged",
      (enabled) => setReduceMotion(enabled),
    );
    return () => {
      mounted = false;
      subscription.remove();
    };
  }, []);

  const [mode, setMode] = useState<"review" | "adjust">("review");
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Adjust drafts. Value fields are strings (editable text); amount is numeric.
  const parsedAmount = item.amount ?? 1;
  const [amountDraft, setAmountDraft] = useState(parsedAmount);
  const [valueDrafts, setValueDrafts] = useState<Record<ValueFieldKey, string>>(
    () => makeValueDrafts(item),
  );

  // Reset transient state and drafts when the sheet re-opens or targets a new
  // item. Uses the render-time prop-change pattern (no effect) so a re-open
  // never carries stale edits or an error from the last proposal.
  const [prevVisible, setPrevVisible] = useState(visible);
  const [syncedItemId, setSyncedItemId] = useState(item.id);
  if (visible !== prevVisible || item.id !== syncedItemId) {
    setPrevVisible(visible);
    setSyncedItemId(item.id);
    if (visible) {
      setMode("review");
      setConfirming(false);
      setError(null);
      setAmountDraft(item.amount ?? 1);
      setValueDrafts(makeValueDrafts(item));
    }
  }

  const source = item.source ?? null;
  const provenance = provenancePresentation(source, false);
  const sourceLabel = source?.label ?? "Label scan";

  // Assemble the adjusted-value payload from the drafts, including only fields
  // the user actually changed — so an unchanged confirm sends an empty body and
  // keeps the parse un-edited (is_edited stays false), while a real edit commits
  // as the user's own number.
  const buildAdjustments = useCallback((): LabelProposalAdjustments => {
    const adjustments: Record<string, number> = {};
    for (const { key } of VALUE_FIELDS) {
      const parsedValue = item[key];
      const draft = valueDrafts[key].trim();
      if (draft === "") continue;
      const parsed = Number(draft);
      if (!Number.isFinite(parsed) || parsed < 0) continue;
      if (parsedValue === null || !approxEqual(parsed, parsedValue)) {
        adjustments[key] = parsed;
      }
    }
    if (!approxEqual(amountDraft, parsedAmount)) {
      adjustments.amount = amountDraft;
    }
    return adjustments;
  }, [item, valueDrafts, amountDraft, parsedAmount]);

  const submitConfirm = useCallback(
    async (adjustments: LabelProposalAdjustments) => {
      setConfirming(true);
      setError(null);
      try {
        const committed = await confirm(session, item.log_event_id, adjustments);
        onConfirmed(committed);
      } catch (err) {
        setError(messageForError(err));
      } finally {
        setConfirming(false);
      }
    },
    [confirm, session, item.log_event_id, onConfirmed],
  );

  const handleLooksRight = useCallback(() => {
    void submitConfirm({});
  }, [submitConfirm]);

  const handleAddAdjusted = useCallback(() => {
    void submitConfirm(buildAdjustments());
  }, [submitConfirm, buildAdjustments]);

  const stepAmount = useCallback((delta: number) => {
    setAmountDraft((current) =>
      Math.max(MIN_AMOUNT, Math.round((current + delta) * 4) / 4),
    );
  }, []);

  const animationType = reduceMotion === false ? "slide" : "none";

  const valuesA11yLabel = [
    item.name,
    `${item.calories !== null ? Math.round(item.calories) : "unknown"} calories`,
    `${formatValue(item.protein_g)} grams protein`,
    `${formatValue(item.carbs_g)} grams carbs`,
    `${formatValue(item.fat_g)} grams fat`,
    servingDisplay(item),
    "not yet counted",
    `from ${sourceLabel}`,
  ].join(", ");

  return (
    <Modal
      visible={visible}
      transparent
      animationType={animationType}
      presentationStyle="overFullScreen"
      onRequestClose={onClose}
      accessibilityViewIsModal
    >
      <View style={styles.overlay}>
        <Pressable
          style={StyleSheet.absoluteFill}
          onPress={onClose}
          accessibilityLabel="Close without adding"
          accessibilityHint="Leaves this label parse uncounted; you can confirm it later"
          accessibilityRole={"button" as AccessibilityRole}
        />

        <View style={[styles.sheet, { backgroundColor: colors.surfaceRaised }]}>
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
              <Text style={[styles.closeLabel, { color: colors.accentText }]}>Not now</Text>
            </Pressable>
          </View>

          <ScrollView
            style={styles.scrollContent}
            contentContainerStyle={styles.scrollInner}
            keyboardShouldPersistTaps="handled"
            showsVerticalScrollIndicator={false}
          >
            {/* Provenance + not-yet-counted state */}
            <View
              style={styles.metaRow}
              accessibilityRole="summary"
              accessibilityLabel={valuesA11yLabel}
            >
              <View style={styles.provenanceRow}>
                <AppIcon
                  name={provenance.icon}
                  size={16}
                  color={colors.textMuted}
                  accessibilityLabel={provenance.accessibilityLabel}
                />
                <Text style={[styles.provenanceLabel, { color: colors.textSecondary }]}>
                  {sourceLabel}
                </Text>
              </View>
              <View
                style={[styles.notCountedBadge, { backgroundColor: colors.controlBackground }]}
              >
                <Text style={[styles.notCountedText, { color: colors.textSecondary }]}>
                  Not yet counted
                </Text>
              </View>
            </View>

            <Text style={[styles.helperText, { color: colors.textMuted }]}>
              Check the parsed values before this counts toward today.
            </Text>

            {/* Values */}
            {mode === "review" ? (
              <ReviewValues item={item} colors={colors} />
            ) : (
              <AdjustValues
                item={item}
                amount={amountDraft}
                onStepDown={() => stepAmount(-AMOUNT_STEP)}
                onStepUp={() => stepAmount(AMOUNT_STEP)}
                valueDrafts={valueDrafts}
                onChangeValue={(key, text) =>
                  setValueDrafts((prev) => ({ ...prev, [key]: text }))
                }
                editable={!confirming}
                colors={colors}
              />
            )}

            {error ? (
              <Text
                style={[styles.errorText, { color: colors.coral }]}
                accessibilityRole="alert"
              >
                {error}
              </Text>
            ) : null}

            {/* Actions */}
            {mode === "review" ? (
              <View style={styles.actions}>
                <Pressable
                  onPress={() => {
                    setError(null);
                    setMode("adjust");
                  }}
                  style={[styles.secondaryButton, { backgroundColor: colors.controlBackground }]}
                  accessibilityRole="button"
                  accessibilityLabel="Adjust values"
                  accessibilityHint="Edit the calories, macros, or serving before adding"
                  disabled={confirming}
                >
                  <Text style={[styles.secondaryLabel, { color: colors.text }]}>
                    Adjust
                  </Text>
                </Pressable>
                <Pressable
                  onPress={handleLooksRight}
                  style={[styles.primaryButton, { backgroundColor: colors.accent }]}
                  accessibilityRole="button"
                  accessibilityLabel="Looks right, add it"
                  accessibilityHint="Confirms the parsed values so they count toward today"
                  disabled={confirming}
                  accessibilityState={{ disabled: confirming }}
                >
                  <Text style={[styles.primaryLabel, { color: colors.accentForeground }]}>
                    {confirming ? "Adding…" : "Looks right"}
                  </Text>
                </Pressable>
              </View>
            ) : (
              <View style={styles.actions}>
                <Pressable
                  onPress={() => {
                    setError(null);
                    setAmountDraft(item.amount ?? 1);
                    setValueDrafts(makeValueDrafts(item));
                    setMode("review");
                  }}
                  style={[styles.secondaryButton, { backgroundColor: colors.controlBackground }]}
                  accessibilityRole="button"
                  accessibilityLabel="Cancel adjustments"
                  disabled={confirming}
                >
                  <Text style={[styles.secondaryLabel, { color: colors.text }]}>
                    Cancel
                  </Text>
                </Pressable>
                <Pressable
                  onPress={handleAddAdjusted}
                  style={[styles.primaryButton, { backgroundColor: colors.accent }]}
                  accessibilityRole="button"
                  accessibilityLabel="Add adjusted values"
                  accessibilityHint="Commits your corrected values so they count toward today"
                  disabled={confirming}
                  accessibilityState={{ disabled: confirming }}
                >
                  <Text style={[styles.primaryLabel, { color: colors.accentForeground }]}>
                    {confirming ? "Adding…" : "Add adjusted"}
                  </Text>
                </Pressable>
              </View>
            )}
          </ScrollView>
        </View>
      </View>
    </Modal>
  );
}

/** Seed the value drafts from the parsed item (blank for an absent value). */
function makeValueDrafts(item: DerivedFoodItemDTO): Record<ValueFieldKey, string> {
  return {
    calories: item.calories !== null ? formatValue(item.calories) : "",
    protein_g: item.protein_g !== null ? formatValue(item.protein_g) : "",
    carbs_g: item.carbs_g !== null ? formatValue(item.carbs_g) : "",
    fat_g: item.fat_g !== null ? formatValue(item.fat_g) : "",
  };
}

/** Equal within the backend's 0.1 display rounding — avoids false "edited" diffs. */
function approxEqual(a: number, b: number): boolean {
  return Math.abs(a - b) < 0.05;
}

// ─── Sub-components ────────────────────────────────────────────────────────────

function ReviewValues({
  item,
  colors,
}: {
  item: DerivedFoodItemDTO;
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  return (
    <View style={styles.valuesBlock}>
      <Text
        style={[styles.servingLabel, { color: colors.textSecondary }]}
        accessibilityElementsHidden
      >
        {servingDisplay(item)}
      </Text>
      <ThemedNumber
        value={item.calories !== null ? `${Math.round(item.calories)} kcal` : "— kcal"}
        scale="title2"
        accessibilityElementsHidden
      />
      <View style={styles.macroRow} accessibilityElementsHidden>
        <MacroChip label="P" value={item.protein_g} colors={colors} />
        <MacroChip label="C" value={item.carbs_g} colors={colors} />
        <MacroChip label="F" value={item.fat_g} colors={colors} />
      </View>
    </View>
  );
}

function MacroChip({
  label,
  value,
  colors,
}: {
  label: string;
  value: number | null;
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  return (
    <Text style={[styles.macroChip, { color: colors.textSecondary }]}>
      {`${label} ${formatValue(value)}g`}
    </Text>
  );
}

function AdjustValues({
  item,
  amount,
  onStepDown,
  onStepUp,
  valueDrafts,
  onChangeValue,
  editable,
  colors,
}: {
  item: DerivedFoodItemDTO;
  amount: number;
  onStepDown: () => void;
  onStepUp: () => void;
  valueDrafts: Record<ValueFieldKey, string>;
  onChangeValue: (key: ValueFieldKey, text: string) => void;
  editable: boolean;
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  const amountDisplay = `${formatValue(amount)}${item.unit ? ` ${item.unit}` : ""}`;
  return (
    <View style={styles.adjustBlock}>
      {/* Portion stepper — provenance-preserving rescale on confirm */}
      <Text style={[styles.sectionLabel, { color: colors.textSecondary }]}>
        Servings
      </Text>
      <View style={styles.stepperRow}>
        <Pressable
          onPress={onStepDown}
          style={[styles.stepperButton, { backgroundColor: colors.controlBackground }]}
          accessibilityLabel="Decrease servings"
          accessibilityRole="button"
          disabled={!editable || amount <= MIN_AMOUNT}
          accessibilityState={{ disabled: !editable || amount <= MIN_AMOUNT }}
        >
          <Text style={[styles.stepperButtonLabel, { color: colors.text }]}>−</Text>
        </Pressable>
        <Text
          style={[styles.stepperValue, { color: colors.text }]}
          accessibilityLabel={`Servings: ${amountDisplay}`}
        >
          {amountDisplay}
        </Text>
        <Pressable
          onPress={onStepUp}
          style={[styles.stepperButton, { backgroundColor: colors.controlBackground }]}
          accessibilityLabel="Increase servings"
          accessibilityRole="button"
          disabled={!editable}
          accessibilityState={{ disabled: !editable }}
        >
          <Text style={[styles.stepperButtonLabel, { color: colors.text }]}>+</Text>
        </Pressable>
      </View>

      {/* Value overrides — a changed number commits as the user's own value */}
      <Text style={[styles.sectionLabel, { color: colors.textSecondary }]}>
        Values
      </Text>
      {VALUE_FIELDS.map(({ key, label, unit }) => (
        <View key={key} style={styles.valueFieldRow}>
          <Text style={[styles.valueFieldLabel, { color: colors.textSecondary }]}>
            {label}
          </Text>
          <TextInput
            accessibilityLabel={`${label} value`}
            value={valueDrafts[key]}
            onChangeText={(text) => onChangeValue(key, text)}
            keyboardType="decimal-pad"
            inputMode="decimal"
            editable={editable}
            selectTextOnFocus
            style={[
              styles.valueInput,
              {
                backgroundColor: colors.surface,
                color: colors.text,
                borderColor: colors.separator,
              },
            ]}
          />
          <Text style={[styles.valueUnit, { color: colors.textMuted }]}>{unit}</Text>
        </View>
      ))}
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
    maxHeight: "85%",
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
    flexGrow: 0,
  },
  scrollInner: {
    paddingHorizontal: spacing.base,
    paddingBottom: spacing.xxxl,
    gap: spacing.md,
  },
  metaRow: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: spacing.sm,
  },
  provenanceRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
    flex: 1,
  },
  provenanceLabel: {
    fontSize: typeScale.subhead,
    fontWeight: "500",
  },
  notCountedBadge: {
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 3,
  },
  notCountedText: {
    fontSize: typeScale.caption2,
    fontWeight: "600",
  },
  helperText: {
    fontSize: typeScale.footnote,
  },
  valuesBlock: {
    gap: spacing.xs,
  },
  servingLabel: {
    fontSize: typeScale.subhead,
  },
  macroRow: {
    flexDirection: "row",
    gap: spacing.md,
    flexWrap: "wrap",
  },
  macroChip: {
    fontSize: typeScale.subhead,
    fontVariant: ["tabular-nums"],
  },
  adjustBlock: {
    gap: spacing.sm,
  },
  sectionLabel: {
    fontSize: typeScale.footnote,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.5,
    marginTop: spacing.xs,
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
    fontSize: typeScale.title2,
    fontWeight: "300",
  },
  stepperValue: {
    flex: 1,
    textAlign: "center",
    fontSize: typeScale.title3,
    fontWeight: "600",
    fontVariant: ["tabular-nums"],
  },
  valueFieldRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    minHeight: 44,
  },
  valueFieldLabel: {
    width: 72,
    fontSize: typeScale.callout,
  },
  valueInput: {
    flex: 1,
    height: 44,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: spacing.md,
    fontSize: typeScale.callout,
    textAlign: "right",
    fontVariant: ["tabular-nums"],
  },
  valueUnit: {
    minWidth: 36,
    fontSize: typeScale.subhead,
  },
  actions: {
    flexDirection: "row",
    gap: spacing.sm,
    marginTop: spacing.sm,
  },
  secondaryButton: {
    flex: 1,
    height: 48,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  secondaryLabel: {
    fontSize: typeScale.callout,
    fontWeight: "600",
  },
  primaryButton: {
    flex: 2,
    height: 48,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  primaryLabel: {
    fontSize: typeScale.callout,
    fontWeight: "700",
  },
  errorText: {
    fontSize: typeScale.footnote,
  },
});
