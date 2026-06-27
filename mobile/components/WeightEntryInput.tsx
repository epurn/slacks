import { useState } from "react";
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

interface WeightEntryInputProps {
  unitsPreference: UnitsPreference;
  submitting: boolean;
  submitError: string | null;
  /** Called with the entered weight in the user's display units. */
  onSubmit: (weight: number) => void;
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
}: WeightEntryInputProps) {
  const [weightText, setWeightText] = useState("");
  const unitLabel = weightUnitLabel(unitsPreference);
  const parsed = parseWeightInput(weightText);
  const canSubmit = parsed !== null && !submitting;

  return (
    <View style={styles.container}>
      <View style={styles.inputRow}>
        <TextInput
          accessibilityLabel={`Weight in ${unitLabel}`}
          placeholder="0.0"
          placeholderTextColor="#A0A0A8"
          value={weightText}
          onChangeText={setWeightText}
          keyboardType="decimal-pad"
          editable={!submitting}
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
          <ActivityIndicator color="#FFFFFF" accessibilityLabel="Saving weight" />
        ) : (
          <Text style={styles.buttonLabel}>Log weight</Text>
        )}
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { gap: 12 },
  inputRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
  },
  input: {
    flex: 1,
    height: 44,
    backgroundColor: "#FFFFFF",
    borderRadius: 10,
    paddingHorizontal: 14,
    fontSize: 17,
    color: "#1C1C1E",
  },
  unit: {
    fontSize: 17,
    fontWeight: "500",
    color: "#8E8E93",
    minWidth: 24,
  },
  error: {
    fontSize: 14,
    color: "#C0392B",
    marginLeft: 4,
  },
  button: {
    backgroundColor: "#0A84FF",
    borderRadius: 10,
    paddingVertical: 13,
    alignItems: "center",
    justifyContent: "center",
    minHeight: 44,
  },
  buttonDisabled: {
    backgroundColor: "#9DC9FF",
  },
  buttonLabel: {
    fontSize: 16,
    fontWeight: "600",
    color: "#FFFFFF",
  },
});
