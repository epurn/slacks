import { useCallback, useMemo, useState } from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import {
  DerivedItemApiError,
  editDerivedItem as editDerivedItemApi,
  type DerivedItem,
  type DerivedFoodItemDTO,
} from "@/api/derivedItems";
import { useTheme } from "@/theme/ThemeContext";
import type { ColorPalette } from "@/theme/colors";
import {
  saveFood as saveFoodApi,
  type SavedFoodDTO,
  type NutritionSnapshot,
} from "@/api/savedFoods";
import type { ApiSession } from "@/state/session";
import {
  editFieldsFor,
  fieldCurrentValue,
  fieldEstimatedValue,
  formatValue,
  isFieldEdited,
  optimisticApply,
  type EditableField,
} from "@/state/derivedItems";

/** Map an edit failure to a plain, nonjudgmental message; never echoes a value. */
function messageFor(error: unknown): string {
  if (error instanceof DerivedItemApiError) {
    return error.message;
  }
  return "We couldn't save that correction. Check your connection and try again.";
}

type SaveFoodStatus = "idle" | "saving" | "saved" | "error";

/**
 * The editable food/exercise item surface for the Today timeline (FTY-050).
 *
 * Renders a single derived item's correctable values — calories, macros, and
 * servings for food; active-calories burn for exercise — each with an inline
 * numeric edit control. An edit sends one `PATCH` per field to the FTY-051 edit
 * endpoint and re-renders the **current** values the server returns, including
 * any server-rescaled calories/macros from a servings edit (the UI never
 * computes the rescale).
 *
 * Edits are optimistic: the new value shows immediately, then reconciles with
 * the server response; on failure the row rolls back to the prior value and
 * surfaces a clear error. A corrected field carries an accessible "edited"
 * indicator (text, not color alone) that names the preserved original estimate,
 * so the user can tell at a glance — and by screen reader — which values were
 * changed.
 *
 * For resolved food items, a "Save this food" action (FTY-053) persists the
 * corrected nutrition snapshot via FTY-052's save endpoint, recording the
 * original typed phrase (`logPhrase`) as an alias.
 *
 * The row owns the item's display state after mount and lifts each confirmed
 * server value via `onItemChange`. `edit` and `saveFood` are injectable for tests.
 */
export function EditableItemRow({
  item: initialItem,
  session,
  edit = editDerivedItemApi,
  onItemChange,
  logPhrase,
  saveFood = saveFoodApi,
  onSaved,
}: {
  item: DerivedItem;
  session: ApiSession;
  edit?: typeof editDerivedItemApi;
  onItemChange?: (item: DerivedItem) => void;
  /** The original typed phrase from the log event; enables the Save this food action. */
  logPhrase?: string;
  /** Injectable for tests; saves the corrected food via FTY-052. */
  saveFood?: typeof saveFoodApi;
  /** Called with the saved food after a successful save. */
  onSaved?: (saved: SavedFoodDTO) => void;
}) {
  const { colors } = useTheme();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const [item, setItem] = useState<DerivedItem>(initialItem);
  const [editingField, setEditingField] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveFoodStatus, setSaveFoodStatus] = useState<SaveFoodStatus>("idle");
  const [saveFoodError, setSaveFoodError] = useState<string | null>(null);

  // Resync when the parent supplies a new item (e.g. after lifting a confirmed
  // server value) using the render-phase "adjust state on prop change" pattern.
  // The optimistic path mutates local state, not this prop, so a resync never
  // clobbers an in-flight edit; parents pass stable references.
  const [syncedItem, setSyncedItem] = useState<DerivedItem>(initialItem);
  if (initialItem !== syncedItem) {
    setSyncedItem(initialItem);
    setItem(initialItem);
  }

  const beginEdit = useCallback(
    (field: EditableField) => {
      setError(null);
      setEditingField(field.requestField);
      const current = fieldCurrentValue(item, field);
      setDraft(current === null ? "" : formatValue(current));
    },
    [item],
  );

  const cancelEdit = useCallback(() => {
    setEditingField(null);
    setError(null);
  }, []);

  const submitEdit = useCallback(
    async (field: EditableField) => {
      const parsed = Number(draft.trim());
      // Mirror the server's request-boundary rule (finite, non-negative) for a
      // fast local rejection; the server remains the trust boundary.
      if (draft.trim() === "" || !Number.isFinite(parsed) || parsed < 0) {
        setError("Enter a number that's zero or more.");
        return;
      }

      const prior = item;
      // Optimistic: show the edited field immediately; rescaled siblings (if any)
      // arrive with the server response.
      setItem(optimisticApply(prior, field, parsed));
      setEditingField(null);
      setSaving(true);
      setError(null);
      try {
        const updated = await edit(
          session,
          prior.item_type,
          prior.id,
          field.requestField,
          parsed,
        );
        setItem(updated);
        onItemChange?.(updated);
      } catch (err) {
        setItem(prior);
        setError(messageFor(err));
      } finally {
        setSaving(false);
      }
    },
    [draft, item, edit, session, onItemChange],
  );

  const handleSaveFood = useCallback(async () => {
    if (item.item_type !== "food") return;
    const foodItem = item as DerivedFoodItemDTO;
    if (foodItem.calories === null || !logPhrase) return;

    const nutrition: NutritionSnapshot = {
      calories: foodItem.calories,
      protein_g: foodItem.protein_g,
      carbs_g: foodItem.carbs_g,
      fat_g: foodItem.fat_g,
      serving_size: foodItem.amount ?? 1,
      serving_unit: foodItem.unit ?? "serving",
    };

    setSaveFoodStatus("saving");
    setSaveFoodError(null);
    try {
      const saved = await saveFood(session, {
        name: foodItem.name,
        phrase: logPhrase,
        nutrition,
      });
      setSaveFoodStatus("saved");
      onSaved?.(saved);
    } catch {
      setSaveFoodStatus("error");
      setSaveFoodError("We couldn't save that food. Check your connection and try again.");
    }
  }, [item, logPhrase, saveFood, session, onSaved]);

  const fields = editFieldsFor(item).filter(
    (field) => fieldCurrentValue(item, field) !== null,
  );

  const canSaveFood =
    item.item_type === "food" &&
    (item as DerivedFoodItemDTO).calories !== null &&
    !!logPhrase;

  return (
    <View style={styles.item} accessibilityRole="summary">
      <Text style={styles.name} numberOfLines={2}>
        {item.name}
      </Text>
      {item.quantity_text ? (
        <Text style={styles.quantityText}>{item.quantity_text}</Text>
      ) : null}

      {fields.map((field) => (
        <FieldRow
          key={field.requestField}
          item={item}
          field={field}
          editing={editingField === field.requestField}
          draft={draft}
          saving={saving}
          onChangeDraft={setDraft}
          onBegin={() => beginEdit(field)}
          onSubmit={() => void submitEdit(field)}
          onCancel={cancelEdit}
          colors={colors}
        />
      ))}

      {error ? (
        <Text style={styles.error} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}

      {canSaveFood ? (
        <View style={styles.saveFoodRow}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Save this food"
            accessibilityState={{
              disabled:
                saving ||
                saveFoodStatus === "saving" ||
                saveFoodStatus === "saved",
            }}
            disabled={
              saving ||
              saveFoodStatus === "saving" ||
              saveFoodStatus === "saved"
            }
            onPress={() => void handleSaveFood()}
            style={[
              styles.saveFoodButton,
              saveFoodStatus === "saved" && styles.saveFoodButtonSaved,
            ]}
          >
            <Text style={styles.saveFoodLabel}>
              {saveFoodStatus === "saving"
                ? "Saving…"
                : saveFoodStatus === "saved"
                  ? "Saved ✓"
                  : "Save this food"}
            </Text>
          </Pressable>
          {saveFoodStatus === "error" && saveFoodError ? (
            <Text style={styles.error} accessibilityRole="alert">
              {saveFoodError}
            </Text>
          ) : null}
        </View>
      ) : null}
    </View>
  );
}

function FieldRow({
  item,
  field,
  editing,
  draft,
  saving,
  onChangeDraft,
  onBegin,
  onSubmit,
  onCancel,
  colors,
}: {
  item: DerivedItem;
  field: EditableField;
  editing: boolean;
  draft: string;
  saving: boolean;
  onChangeDraft: (value: string) => void;
  onBegin: () => void;
  onSubmit: () => void;
  onCancel: () => void;
  colors: ColorPalette;
}) {
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const current = fieldCurrentValue(item, field);
  const estimated = fieldEstimatedValue(item, field);
  const edited = isFieldEdited(item, field);
  const unitSuffix = field.unit ? ` ${field.unit}` : "";

  if (editing) {
    return (
      <View style={styles.fieldRow}>
        <Text style={styles.fieldLabel}>{field.label}</Text>
        <View style={styles.editGroup}>
          <TextInput
            accessibilityLabel={`${field.label} value`}
            value={draft}
            onChangeText={onChangeDraft}
            keyboardType="decimal-pad"
            inputMode="decimal"
            autoFocus
            editable={!saving}
            style={styles.input}
          />
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Save ${field.label}`}
            onPress={onSubmit}
            style={styles.saveButton}
          >
            <Text style={styles.saveLabel}>Save</Text>
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel={`Cancel editing ${field.label}`}
            onPress={onCancel}
            style={styles.cancelButton}
          >
            <Text style={styles.cancelLabel}>Cancel</Text>
          </Pressable>
        </View>
      </View>
    );
  }

  // The value's accessibility label carries the edited state and the preserved
  // original estimate, so screen-reader users get the same edited-vs-estimated
  // signal sighted users read from the "Edited" pill — never color alone.
  const valueA11yLabel = edited
    ? `${field.label} ${formatValue(current)}${unitSuffix}, edited from ${formatValue(estimated)}${unitSuffix}`
    : `${field.label} ${formatValue(current)}${unitSuffix}`;

  return (
    <View style={styles.fieldRow}>
      <Text style={styles.fieldLabel}>{field.label}</Text>
      <View style={styles.valueGroup}>
        <View style={styles.valueColumn}>
          <Text
            style={[styles.value, edited && styles.valueEdited]}
            accessibilityLabel={valueA11yLabel}
          >
            {`${formatValue(current)}${unitSuffix}`}
          </Text>
          {edited ? (
            <View style={styles.editedRow}>
              <Text style={styles.editedBadge} accessibilityElementsHidden>
                ✓ Edited
              </Text>
              <Text style={styles.wasNote} accessibilityElementsHidden>
                {`was ${formatValue(estimated)}${unitSuffix}`}
              </Text>
            </View>
          ) : null}
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel={`Edit ${field.label}`}
          accessibilityState={{ disabled: saving }}
          disabled={saving}
          onPress={onBegin}
          style={styles.editButton}
        >
          <Text style={styles.editLabel}>Edit</Text>
        </Pressable>
      </View>
    </View>
  );
}

function makeStyles(colors: ColorPalette) {
  return StyleSheet.create({
    item: {
      paddingTop: 8,
      paddingLeft: 36,
      paddingRight: 16,
      paddingBottom: 4,
    },
    name: {
      fontSize: 15,
      fontWeight: "600",
      color: colors.text,
    },
    quantityText: {
      fontSize: 13,
      color: colors.textMuted,
      marginTop: 1,
      marginBottom: 4,
    },
    fieldRow: {
      flexDirection: "row",
      alignItems: "center",
      justifyContent: "space-between",
      minHeight: 36,
      gap: 8,
    },
    fieldLabel: {
      fontSize: 14,
      color: colors.textSecondary,
      width: 76,
    },
    valueGroup: {
      flex: 1,
      flexDirection: "row",
      alignItems: "center",
      justifyContent: "flex-end",
      gap: 10,
    },
    valueColumn: {
      alignItems: "flex-end",
    },
    value: {
      fontSize: 15,
      color: colors.text,
      fontVariant: ["tabular-nums"],
    },
    valueEdited: {
      fontWeight: "700",
    },
    editedRow: {
      flexDirection: "row",
      alignItems: "center",
      gap: 6,
      marginTop: 1,
    },
    editedBadge: {
      fontSize: 11,
      fontWeight: "700",
      color: colors.accentText,
    },
    wasNote: {
      fontSize: 11,
      color: colors.textMuted,
    },
    editGroup: {
      flex: 1,
      flexDirection: "row",
      alignItems: "center",
      justifyContent: "flex-end",
      gap: 8,
    },
    input: {
      minWidth: 72,
      minHeight: 36,
      backgroundColor: colors.surfaceRaised,
      borderWidth: StyleSheet.hairlineWidth,
      borderColor: colors.separator,
      borderRadius: 8,
      paddingHorizontal: 10,
      paddingVertical: 6,
      fontSize: 15,
      color: colors.text,
      textAlign: "right",
    },
    saveButton: {
      paddingVertical: 8,
      paddingHorizontal: 12,
      borderRadius: 8,
      backgroundColor: colors.accent,
      minHeight: 36,
      justifyContent: "center",
    },
    saveLabel: {
      fontSize: 14,
      fontWeight: "600",
      color: colors.accentForeground,
    },
    cancelButton: {
      paddingVertical: 8,
      paddingHorizontal: 8,
      minHeight: 36,
      justifyContent: "center",
    },
    cancelLabel: {
      fontSize: 14,
      color: colors.accent,
    },
    editButton: {
      paddingVertical: 8,
      paddingHorizontal: 10,
      minHeight: 36,
      justifyContent: "center",
    },
    editLabel: {
      fontSize: 14,
      color: colors.accent,
      fontWeight: "500",
    },
    error: {
      fontSize: 13,
      color: colors.coral,
      marginTop: 4,
    },
    saveFoodRow: {
      marginTop: 8,
      marginBottom: 4,
      gap: 6,
    },
    saveFoodButton: {
      alignSelf: "flex-start",
      paddingVertical: 6,
      paddingHorizontal: 14,
      borderRadius: 8,
      backgroundColor: colors.controlBackground,
    },
    saveFoodButtonSaved: {
      // Distinct from the default control fill so the saved state reads as a
      // subtle raised confirmation in both light and dark (not a no-op).
      backgroundColor: colors.surfaceRaised,
    },
    saveFoodLabel: {
      fontSize: 13,
      fontWeight: "500",
      color: colors.textSecondary,
    },
  });
}
