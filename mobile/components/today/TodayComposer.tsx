import {
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { type SavedFoodDTO } from "@/api/savedFoods";
import { searchSavedFoods as searchSavedFoodsApi } from "@/api/savedFoods";
import { AppIcon } from "@/components/ui";
import { TypeaheadSuggestionBar } from "@/components/TypeaheadSuggestionBar";
import { type ApiSession } from "@/state/session";
import { useTheme, spacing, typeScale, radius } from "@/theme";

import { MAX_RAW_TEXT_LENGTH } from "./helpers";

/**
 * Today's natural-language composer: the multiline text field, the barcode /
 * label-capture / add actions, the saved-food typeahead bar, and the inline
 * submit-error alert. A pure view block — the screen shell owns the compose
 * state and hands it the value + callbacks.
 */
export function TodayComposer({
  inputRef,
  text,
  onChangeText,
  submitting,
  canSubmit,
  apiSession,
  searchSavedFoods,
  onSelectSavedFood,
  onScan,
  onCaptureLabel,
  onSubmit,
  submitError,
}: {
  inputRef: React.RefObject<TextInput | null>;
  text: string;
  onChangeText: (value: string) => void;
  submitting: boolean;
  canSubmit: boolean;
  apiSession: ApiSession | null;
  searchSavedFoods: typeof searchSavedFoodsApi;
  onSelectSavedFood: (food: SavedFoodDTO) => void;
  onScan: () => void;
  onCaptureLabel: () => void;
  onSubmit: () => void;
  submitError: string | null;
}) {
  const { colors } = useTheme();

  return (
    <>
      <View style={styles.composer}>
        <TextInput
          ref={inputRef}
          accessibilityLabel="Log food or exercise"
          placeholder="Add food or exercise…"
          placeholderTextColor={colors.textMuted}
          value={text}
          onChangeText={onChangeText}
          multiline
          maxLength={MAX_RAW_TEXT_LENGTH}
          editable={!submitting}
          style={[styles.input, { backgroundColor: colors.surfaceRaised, color: colors.text }]}
        />
        <View style={styles.composerActions}>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Scan barcode"
            accessibilityHint="Opens the camera to scan a product barcode"
            accessibilityState={{ disabled: submitting }}
            disabled={submitting}
            onPress={onScan}
            style={[styles.scanButton, { backgroundColor: colors.controlBackground }]}
          >
            <AppIcon
              name="barcode.viewfinder"
              size={20}
              color={colors.text}
            />
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Capture label"
            accessibilityHint="Opens the camera to photograph a nutrition label"
            accessibilityState={{ disabled: submitting || !apiSession }}
            disabled={submitting || !apiSession}
            onPress={onCaptureLabel}
            style={[styles.scanButton, { backgroundColor: colors.controlBackground }]}
          >
            <AppIcon
              name="camera.fill"
              size={20}
              color={colors.text}
            />
          </Pressable>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Add entry"
            accessibilityState={{ disabled: !canSubmit }}
            disabled={!canSubmit}
            onPress={onSubmit}
            style={[
              styles.add,
              { backgroundColor: canSubmit ? colors.accent : colors.controlBackground },
            ]}
          >
            <Text style={[styles.addLabel, { color: canSubmit ? colors.accentForeground : colors.textMuted }]}>
              {submitting ? "Adding…" : "Add"}
            </Text>
          </Pressable>
        </View>
      </View>
      <TypeaheadSuggestionBar
        query={text}
        session={apiSession}
        onSelect={onSelectSavedFood}
        search={searchSavedFoods}
      />
      {submitError ? (
        <Text style={[styles.error, { color: colors.coral }]} accessibilityRole="alert">
          {submitError}
        </Text>
      ) : null}
    </>
  );
}

const styles = StyleSheet.create({
  composer: {
    flexDirection: "row",
    alignItems: "flex-end",
    gap: spacing.sm,
    marginTop: spacing.sm,
    marginBottom: spacing.base,
  },
  composerActions: {
    flexDirection: "row",
    gap: spacing.xs,
    alignItems: "flex-end",
  },
  scanButton: {
    width: 44,
    height: 44,
    borderRadius: radius.md,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 44,
    minWidth: 44,
  },
  input: {
    flex: 1,
    minHeight: 44,
    maxHeight: 120,
    borderRadius: radius.md,
    paddingHorizontal: 14,
    paddingVertical: spacing.md,
    fontSize: typeScale.body,
  },
  add: {
    borderRadius: radius.md,
    paddingVertical: spacing.md,
    paddingHorizontal: 18,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 44,
  },
  addLabel: {
    fontSize: typeScale.callout,
    fontWeight: "600",
    color: "#FFFFFF",
  },
  error: {
    fontSize: typeScale.footnote,
    marginBottom: spacing.md,
    marginLeft: spacing.xs,
  },
});
