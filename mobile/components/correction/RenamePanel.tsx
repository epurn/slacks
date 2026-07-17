/**
 * FTY-378: In-sheet rename panel — the inline single-line editor for the item's
 * display name, opened from the sheet header's rename affordance. Consistent
 * with `OverridePanel`'s layout and copy weight. Persists via the FTY-377
 * rename endpoint (an audited name edit, not a value override — the item's
 * numbers and source provenance are untouched).
 *
 * Privacy: the name is sensitive user text. It is never logged; an API failure
 * renders the calm mapped copy (HTTP status + action only, never the name).
 */

import { Pressable, StyleSheet, Text, TextInput, View } from "react-native";

import { MAX_ITEM_NAME_LENGTH } from "@/api/derivedItems";
import { DisplayText } from "@/components/ui/DisplayText";
import { radius, spacing, typeScale, type ColorPalette } from "@/theme";

export function RenamePanel({
  draft,
  saving,
  error,
  canSave,
  onChangeDraft,
  onSubmit,
  onCancel,
  colors,
}: {
  draft: string;
  saving: boolean;
  error: string | null;
  canSave: boolean;
  onChangeDraft: (v: string) => void;
  onSubmit: () => void;
  onCancel: () => void;
  colors: ColorPalette;
}) {
  return (
    <View style={styles.panel}>
      <View style={styles.panelHeader}>
        <DisplayText scale="headline">Rename item</DisplayText>
        <Text style={[styles.panelNote, { color: colors.textMuted }]}>
          Values and source stay unchanged
        </Text>
      </View>

      <TextInput
        accessibilityLabel="Item name"
        value={draft}
        onChangeText={onChangeDraft}
        autoFocus
        editable={!saving}
        maxLength={MAX_ITEM_NAME_LENGTH}
        returnKeyType="done"
        onSubmitEditing={() => {
          if (canSave) onSubmit();
        }}
        style={[
          styles.input,
          {
            backgroundColor: colors.surfaceRaised,
            color: colors.text,
            borderColor: colors.separator,
          },
        ]}
        selectTextOnFocus
      />

      {error ? (
        <Text style={[styles.errorText, { color: colors.coral }]} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}

      <View style={styles.actions}>
        <Pressable
          onPress={onCancel}
          style={[styles.cancelBtn, { backgroundColor: colors.controlBackground }]}
          accessibilityRole="button"
          accessibilityLabel="Cancel rename"
          disabled={saving}
        >
          <Text style={[styles.cancelLabel, { color: colors.textSecondary }]}>
            Cancel
          </Text>
        </Pressable>
        <Pressable
          onPress={onSubmit}
          style={[
            styles.saveBtn,
            { backgroundColor: colors.accent },
            canSave ? null : styles.saveBtnDisabled,
          ]}
          accessibilityRole="button"
          accessibilityLabel="Save name"
          disabled={!canSave}
          accessibilityState={{ disabled: !canSave }}
        >
          <Text style={[styles.saveLabel, { color: colors.accentForeground }]}>
            {saving ? "Saving…" : "Save"}
          </Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  panel: {
    paddingHorizontal: spacing.base,
    paddingVertical: spacing.md,
    gap: spacing.md,
  },
  panelHeader: {
    gap: spacing.xs,
  },
  panelNote: {
    fontSize: typeScale.footnote,
  },
  input: {
    height: 48,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    paddingHorizontal: spacing.md,
    fontSize: typeScale.callout,
  },
  errorText: {
    fontSize: typeScale.footnote,
  },
  actions: {
    flexDirection: "row",
    gap: spacing.sm,
  },
  cancelBtn: {
    flex: 1,
    height: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  cancelLabel: {
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  saveBtn: {
    flex: 1,
    height: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
  },
  saveBtnDisabled: {
    opacity: 0.4,
  },
  saveLabel: {
    fontSize: typeScale.callout,
    fontWeight: "600",
  },
});
