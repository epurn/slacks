import { useCallback, useState } from "react";
import {
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import {
  METABOLIC_FORMULA_OPTIONS,
  emptyProfileForm,
  validateProfileForm,
  type ProfileFormErrors,
  type ProfileFormState,
  type ProfileUpdatePayload,
  type UnitsPreference,
} from "@/state/profile";

/**
 * The minimal required profile capture form (FTY-021).
 *
 * iOS-first, compact, and nonjudgmental: it collects height, weight, birth
 * year, a metabolic-formula calculation preference, units, and timezone, then
 * hands the validated *canonical* payload (metres, kilograms) to `onSubmit`.
 * All validation and unit conversion live in `@/state/profile`; this component
 * is the accessible presentation layer over it.
 */
export interface ProfileFormProps {
  /** Current year, injected so validation stays deterministic and testable. */
  readonly currentYear: number;
  /** Device IANA timezone, captured as the profile's timezone. */
  readonly timezone: string;
  /** Initial units preference (defaulted from the device locale). */
  readonly initialUnits?: UnitsPreference;
  /** Called with the canonical payload when the form validates. */
  readonly onSubmit: (payload: ProfileUpdatePayload) => void | Promise<void>;
  /** Whether a save is in flight (disables the submit affordance). */
  readonly submitting?: boolean;
  /** A save error to surface above the submit button. */
  readonly submitError?: string | null;
}

export function ProfileForm({
  currentYear,
  timezone,
  initialUnits = "metric",
  onSubmit,
  submitting = false,
  submitError = null,
}: ProfileFormProps) {
  const insets = useSafeAreaInsets();
  const [form, setForm] = useState<ProfileFormState>(() =>
    emptyProfileForm(initialUnits, timezone),
  );
  const [errors, setErrors] = useState<ProfileFormErrors>({});

  const update = useCallback(
    <K extends keyof ProfileFormState>(key: K, value: ProfileFormState[K]) => {
      setForm((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const setUnits = useCallback((units: UnitsPreference) => {
    // Switching units clears the now-mismatched height/weight entries so a
    // stale metric value is never reinterpreted as imperial.
    setForm((prev) => ({
      ...prev,
      unitsPreference: units,
      heightCm: "",
      heightFeet: "",
      heightInches: "",
      weight: "",
    }));
  }, []);

  const handleSubmit = useCallback(() => {
    const result = validateProfileForm(form, currentYear);
    if (!result.ok) {
      setErrors(result.errors);
      return;
    }
    setErrors({});
    void onSubmit(result.payload);
  }, [form, currentYear, onSubmit]);

  const isMetric = form.unitsPreference === "metric";

  return (
    <ScrollView
      style={styles.screen}
      contentContainerStyle={[
        styles.content,
        { paddingTop: insets.top + 12, paddingBottom: insets.bottom + 32 },
      ]}
      keyboardShouldPersistTaps="handled"
    >
      <Text style={styles.title} accessibilityRole="header">
        Your profile
      </Text>
      <Text style={styles.subtitle}>
        A few details let us estimate your daily targets. Only what the
        calculation needs.
      </Text>

      <Field label="Units">
        <Segmented<UnitsPreference>
          accessibilityLabel="Units preference"
          options={[
            { value: "metric", label: "Metric" },
            { value: "imperial", label: "Imperial" },
          ]}
          selected={form.unitsPreference}
          onSelect={setUnits}
        />
      </Field>

      <Field label="Height" error={errors.height}>
        {isMetric ? (
          <NumberInput
            accessibilityLabel="Height in centimetres"
            placeholder="Centimetres"
            value={form.heightCm}
            onChangeText={(t) => update("heightCm", t)}
            invalid={Boolean(errors.height)}
          />
        ) : (
          <View style={styles.row}>
            <View style={styles.rowItem}>
              <NumberInput
                accessibilityLabel="Height in feet"
                placeholder="Feet"
                value={form.heightFeet}
                onChangeText={(t) => update("heightFeet", t)}
                invalid={Boolean(errors.height)}
              />
            </View>
            <View style={styles.rowItem}>
              <NumberInput
                accessibilityLabel="Height in inches"
                placeholder="Inches"
                value={form.heightInches}
                onChangeText={(t) => update("heightInches", t)}
                invalid={Boolean(errors.height)}
              />
            </View>
          </View>
        )}
      </Field>

      <Field label="Weight" error={errors.weight}>
        <NumberInput
          accessibilityLabel={isMetric ? "Weight in kilograms" : "Weight in pounds"}
          placeholder={isMetric ? "Kilograms" : "Pounds"}
          value={form.weight}
          onChangeText={(t) => update("weight", t)}
          invalid={Boolean(errors.weight)}
        />
      </Field>

      <Field label="Birth year" error={errors.birthYear}>
        <NumberInput
          accessibilityLabel="Birth year"
          placeholder="e.g. 1990"
          value={form.birthYear}
          onChangeText={(t) => update("birthYear", t)}
          invalid={Boolean(errors.birthYear)}
          maxLength={4}
        />
      </Field>

      <Field
        label="Calculation preference"
        hint="Used only to pick the resting-metabolism formula. Not a clinical question."
        error={errors.metabolicFormula}
      >
        <View
          accessibilityRole="radiogroup"
          accessibilityLabel="Calculation preference"
        >
          {METABOLIC_FORMULA_OPTIONS.map((option) => {
            const selected = form.metabolicFormula === option.value;
            return (
              <Pressable
                key={option.value}
                accessibilityRole="radio"
                accessibilityState={{ selected }}
                accessibilityLabel={`${option.label}. ${option.description}`}
                onPress={() => update("metabolicFormula", option.value)}
                style={[styles.choice, selected && styles.choiceSelected]}
              >
                <Text
                  style={[
                    styles.choiceLabel,
                    selected && styles.choiceLabelSelected,
                  ]}
                >
                  {option.label}
                </Text>
                <Text style={styles.choiceDescription}>
                  {option.description}
                </Text>
              </Pressable>
            );
          })}
        </View>
      </Field>

      <Field label="Timezone" error={errors.timezone}>
        <View style={styles.readonly}>
          <Text style={styles.readonlyValue} accessibilityLabel={`Timezone ${form.timezone}`}>
            {form.timezone}
          </Text>
        </View>
      </Field>

      {submitError ? (
        <Text style={styles.submitError} accessibilityRole="alert">
          {submitError}
        </Text>
      ) : null}

      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Save profile"
        accessibilityState={{ disabled: submitting }}
        disabled={submitting}
        onPress={handleSubmit}
        style={[styles.submit, submitting && styles.submitDisabled]}
      >
        <Text style={styles.submitLabel}>
          {submitting ? "Saving…" : "Save profile"}
        </Text>
      </Pressable>
    </ScrollView>
  );
}

function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <View style={styles.field}>
      <Text style={styles.fieldLabel} accessibilityRole="header">
        {label}
      </Text>
      {hint ? <Text style={styles.fieldHint}>{hint}</Text> : null}
      {children}
      {error ? (
        <Text style={styles.fieldError} accessibilityRole="alert">
          {error}
        </Text>
      ) : null}
    </View>
  );
}

function NumberInput({
  accessibilityLabel,
  placeholder,
  value,
  onChangeText,
  invalid,
  maxLength,
}: {
  accessibilityLabel: string;
  placeholder: string;
  value: string;
  onChangeText: (text: string) => void;
  invalid?: boolean;
  maxLength?: number;
}) {
  return (
    <TextInput
      accessibilityLabel={accessibilityLabel}
      placeholder={placeholder}
      placeholderTextColor="#A0A0A8"
      value={value}
      onChangeText={onChangeText}
      keyboardType="numeric"
      inputMode="numeric"
      maxLength={maxLength}
      style={[styles.input, invalid && styles.inputInvalid]}
    />
  );
}

function Segmented<T extends string>({
  accessibilityLabel,
  options,
  selected,
  onSelect,
}: {
  accessibilityLabel: string;
  options: readonly { value: T; label: string }[];
  selected: T;
  onSelect: (value: T) => void;
}) {
  return (
    <View
      style={styles.segmented}
      accessibilityRole="radiogroup"
      accessibilityLabel={accessibilityLabel}
    >
      {options.map((option) => {
        const isSelected = option.value === selected;
        return (
          <Pressable
            key={option.value}
            accessibilityRole="radio"
            accessibilityState={{ selected: isSelected }}
            accessibilityLabel={option.label}
            onPress={() => onSelect(option.value)}
            style={[
              styles.segment,
              isSelected && styles.segmentSelected,
            ]}
          >
            <Text
              style={[
                styles.segmentLabel,
                isSelected && styles.segmentLabelSelected,
              ]}
            >
              {option.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: "#F2F2F7",
  },
  content: {
    paddingHorizontal: 16,
  },
  title: {
    fontSize: 34,
    fontWeight: "700",
    color: "#1C1C1E",
  },
  subtitle: {
    fontSize: 15,
    color: "#8E8E93",
    marginTop: 4,
    marginBottom: 16,
  },
  field: {
    marginBottom: 18,
  },
  fieldLabel: {
    fontSize: 13,
    fontWeight: "600",
    textTransform: "uppercase",
    letterSpacing: 0.5,
    color: "#8E8E93",
    marginBottom: 6,
    marginLeft: 4,
  },
  fieldHint: {
    fontSize: 13,
    color: "#8E8E93",
    marginBottom: 8,
    marginLeft: 4,
  },
  fieldError: {
    fontSize: 13,
    color: "#C0392B",
    marginTop: 6,
    marginLeft: 4,
  },
  input: {
    backgroundColor: "#FFFFFF",
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 17,
    color: "#1C1C1E",
    borderWidth: 1,
    borderColor: "#FFFFFF",
  },
  inputInvalid: {
    borderColor: "#C0392B",
  },
  row: {
    flexDirection: "row",
    gap: 12,
  },
  rowItem: {
    flex: 1,
  },
  segmented: {
    flexDirection: "row",
    backgroundColor: "#E4E4EA",
    borderRadius: 10,
    padding: 2,
    gap: 2,
  },
  segment: {
    flex: 1,
    paddingVertical: 10,
    borderRadius: 8,
    alignItems: "center",
  },
  segmentSelected: {
    backgroundColor: "#FFFFFF",
  },
  segmentLabel: {
    fontSize: 15,
    color: "#3A3A3C",
    fontWeight: "500",
  },
  segmentLabelSelected: {
    color: "#1C1C1E",
    fontWeight: "600",
  },
  choice: {
    backgroundColor: "#FFFFFF",
    borderRadius: 10,
    padding: 14,
    marginBottom: 8,
    borderWidth: 1,
    borderColor: "#FFFFFF",
  },
  choiceSelected: {
    borderColor: "#0A84FF",
  },
  choiceLabel: {
    fontSize: 16,
    fontWeight: "600",
    color: "#1C1C1E",
  },
  choiceLabelSelected: {
    color: "#0A84FF",
  },
  choiceDescription: {
    fontSize: 13,
    color: "#8E8E93",
    marginTop: 2,
  },
  readonly: {
    backgroundColor: "#FFFFFF",
    borderRadius: 10,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  readonlyValue: {
    fontSize: 17,
    color: "#1C1C1E",
  },
  submitError: {
    fontSize: 14,
    color: "#C0392B",
    marginBottom: 12,
    marginLeft: 4,
  },
  submit: {
    backgroundColor: "#0A84FF",
    borderRadius: 12,
    paddingVertical: 16,
    alignItems: "center",
    marginTop: 4,
  },
  submitDisabled: {
    backgroundColor: "#9DC9FF",
  },
  submitLabel: {
    fontSize: 17,
    fontWeight: "600",
    color: "#FFFFFF",
  },
});
