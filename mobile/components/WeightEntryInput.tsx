import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import type { UnitsPreference } from "@/state/profile";
import { parseWeightInput, weightUnitLabel } from "@/state/weightEntries";
import { useTheme } from "@/theme/ThemeContext";
import type { ColorPalette } from "@/theme/colors";

interface WeightEntryInputProps {
  unitsPreference: UnitsPreference;
  submitting: boolean;
  submitError: string | null;
  /** Called with the entered weight in the user's display units. */
  onSubmit: (weight: number) => void;
  /**
   * Optional seed value in display units. Used by WeightLogSheet (FTY-101) to
   * pre-fill the input with the user's last logged weight.
   */
  initialValue?: number;
  /**
   * Raise the keyboard on mount. Weight logging is a deliberate single-field
   * entry sheet (FTY-183), so the field auto-focuses on present — distinct from
   * the Today composer, which never auto-raises the keyboard.
   */
  autoFocus?: boolean;
}

/**
 * Weight-entry input for FTY-074. Accepts a body-weight value in the user's
 * preferred units (kg or lb), validates that it is a positive number, and calls
 * `onSubmit` with the parsed value. The parent is responsible for the API call;
 * this component owns only the input state and inline validation feedback.
 *
 * Privacy: the entered weight is never echoed into log or error output here.
 */
export function WeightEntryInput({
  unitsPreference,
  submitting,
  submitError,
  onSubmit,
  initialValue,
  autoFocus = false,
}: WeightEntryInputProps) {
  const { colors } = useTheme();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const [weightText, setWeightText] = useState(
    initialValue != null ? String(initialValue) : "",
  );
  const unitLabel = weightUnitLabel(unitsPreference);
  const parsed = parseWeightInput(weightText);
  const canSubmit = parsed !== null && !submitting;

  return (
    <View style={styles.container}>
      <View style={styles.inputRow}>
        <TextInput
          accessibilityLabel={`Weight in ${unitLabel}`}
          placeholder="0.0"
          placeholderTextColor={colors.textMuted}
          value={weightText}
          onChangeText={setWeightText}
          keyboardType="decimal-pad"
          editable={!submitting}
          autoFocus={autoFocus}
          selectTextOnFocus
          style={styles.input}
        />
        <Text style={styles.unit} importantForAccessibility="no">
          {unitLabel}
        </Text>
      </View>
      {submitError ? (
        <Text style={styles.error} accessibilityRole="alert">
          {submitError}
        </Text>
      ) : null}
      <Pressable
        testID="weight-log-submit"
        accessibilityRole="button"
        accessibilityLabel="Log weight"
        accessibilityState={{ disabled: !canSubmit }}
        disabled={!canSubmit}
        onPress={() => {
          if (parsed !== null) onSubmit(parsed);
        }}
        style={[styles.button, !canSubmit && styles.buttonDisabled]}
      >
        {submitting ? (
          <ActivityIndicator color={colors.accentForeground} accessibilityLabel="Saving weight" />
        ) : (
          <Text style={styles.buttonLabel}>Log weight</Text>
        )}
      </Pressable>
    </View>
  );
}

function makeStyles(colors: ColorPalette) {
  return StyleSheet.create({
    container: { gap: 12 },
    inputRow: {
      flexDirection: "row",
      alignItems: "center",
      gap: 8,
    },
    input: {
      flex: 1,
      height: 44,
      backgroundColor: colors.surfaceRaised,
      borderRadius: 10,
      paddingHorizontal: 14,
      fontSize: 17,
      color: colors.text,
    },
    unit: {
      fontSize: 17,
      fontWeight: "500",
      color: colors.textMuted,
      minWidth: 24,
    },
    error: {
      fontSize: 14,
      color: colors.coral,
      marginLeft: 4,
    },
    button: {
      backgroundColor: colors.accent,
      borderRadius: 10,
      paddingVertical: 13,
      alignItems: "center",
      justifyContent: "center",
      minHeight: 44,
    },
    buttonDisabled: {
      backgroundColor: colors.controlBackground,
    },
    buttonLabel: {
      fontSize: 16,
      fontWeight: "600",
      color: colors.accentForeground,
    },
  });
}
