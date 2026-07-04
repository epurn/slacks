/**
 * Onboarding step 2 — body measurements (FTY-103).
 *
 * Extracted from `OnboardingScreen.tsx` (FTY-206). Presentation only: the
 * wizard hook owns the measurement values, validation errors, and save state
 * and hands this section the values plus the field-update / continue callbacks.
 * Units and timezone are auto-detected and shown read-only, not asked.
 */

import { Pressable, Text, TextInput, View } from 'react-native';

import { Button } from '@/components/ui/Button';
import {
  METABOLIC_FORMULA_OPTIONS,
  type ProfileFormErrors,
} from '@/state/profile';
import type { MeasurementsStepState } from '@/state/onboarding';
import { radius } from '@/theme';

import {
  FieldError,
  LabelledInput,
  SectionLabel,
  StepContainer,
  type ThemeColors,
} from './primitives';
import { styles } from './styles';

export function MeasurementsStep({
  measurements,
  measurementErrors,
  saving,
  saveError,
  isMetric,
  onUpdateMeasurement,
  onContinue,
  colors,
}: {
  measurements: MeasurementsStepState;
  measurementErrors: ProfileFormErrors;
  saving: boolean;
  saveError: string | null;
  isMetric: boolean;
  onUpdateMeasurement: <K extends keyof MeasurementsStepState>(
    key: K,
    value: MeasurementsStepState[K],
  ) => void;
  onContinue: () => void;
  colors: ThemeColors;
}) {
  return (
    <StepContainer>
      <Text
        style={[styles.stepTitle, { color: colors.text }]}
        accessibilityRole="header"
      >
        Your body metrics
      </Text>
      <Text style={[styles.stepSubtitle, { color: colors.textSecondary }]}>
        Used to calculate your resting metabolic rate.
      </Text>

      {/* Auto-detected unit + timezone (read-only, shown for transparency) */}
      <View
        style={[styles.autoDetectRow, { backgroundColor: colors.surfaceRaised, borderRadius: radius.md }]}
      >
        <Text
          style={[styles.autoDetectLabel, { color: colors.textMuted }]}
          accessibilityLabel={`Units: ${isMetric ? 'Metric' : 'Imperial'} (auto-detected from your device)`}
        >
          {`Units: ${isMetric ? 'Metric' : 'Imperial'}`}
        </Text>
        <Text
          style={[styles.autoDetectLabel, { color: colors.textMuted }]}
          accessibilityLabel={`Timezone: ${measurements.timezone} (auto-detected from your device)`}
        >
          {`Timezone: ${measurements.timezone}`}
        </Text>
        <Text style={[styles.autoDetectNote, { color: colors.textMuted }]}>
          Both detected from your device — adjustable later in Profile.
        </Text>
      </View>

      {/* Height */}
      {isMetric ? (
        <LabelledInput
          label="Height (cm)"
          value={measurements.heightCm}
          onChangeText={(v) => onUpdateMeasurement('heightCm', v)}
          keyboardType="numeric"
          error={measurementErrors.height}
          colors={colors}
        />
      ) : (
        <View>
          <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>
            Height
          </Text>
          <View style={styles.imperialHeightRow}>
            <TextInput
              accessibilityLabel="Height feet"
              value={measurements.heightFeet}
              onChangeText={(v) => onUpdateMeasurement('heightFeet', v)}
              keyboardType="numeric"
              inputMode="numeric"
              placeholder="ft"
              placeholderTextColor={colors.textMuted}
              style={[
                styles.textInput,
                styles.imperialHeightInput,
                {
                  backgroundColor: colors.surfaceRaised,
                  color: colors.text,
                  borderColor: measurementErrors.height
                    ? colors.coral
                    : colors.separator,
                },
              ]}
            />
            <TextInput
              accessibilityLabel="Height inches"
              value={measurements.heightInches}
              onChangeText={(v) => onUpdateMeasurement('heightInches', v)}
              keyboardType="numeric"
              inputMode="numeric"
              placeholder="in"
              placeholderTextColor={colors.textMuted}
              style={[
                styles.textInput,
                styles.imperialHeightInput,
                {
                  backgroundColor: colors.surfaceRaised,
                  color: colors.text,
                  borderColor: measurementErrors.height
                    ? colors.coral
                    : colors.separator,
                },
              ]}
            />
          </View>
          {measurementErrors.height && (
            <FieldError message={measurementErrors.height} colors={colors} />
          )}
        </View>
      )}

      {/* Weight */}
      <LabelledInput
        label={`Weight (${isMetric ? 'kg' : 'lb'})`}
        value={measurements.weight}
        onChangeText={(v) => onUpdateMeasurement('weight', v)}
        keyboardType="numeric"
        error={measurementErrors.weight}
        colors={colors}
      />

      {/* Birth year */}
      <LabelledInput
        label="Birth year"
        value={measurements.birthYear}
        onChangeText={(v) => onUpdateMeasurement('birthYear', v)}
        keyboardType="numeric"
        placeholder="e.g. 1990"
        error={measurementErrors.birthYear}
        colors={colors}
      />

      {/* Metabolic formula variant */}
      <SectionLabel label="Calculation preference" colors={colors} />
      <Text style={[styles.formulaNote, { color: colors.textMuted }]}>
        {"The Mifflin-St Jeor formula's sex-dependent constant. Choose the option that better reflects your body composition."}
      </Text>
      {METABOLIC_FORMULA_OPTIONS.map((opt) => {
        const selected = measurements.metabolicFormula === opt.value;
        return (
          <Pressable
            key={opt.value}
            accessibilityRole="radio"
            accessibilityState={{ selected }}
            accessibilityLabel={`${opt.label}. ${opt.description}`}
            onPress={() => onUpdateMeasurement('metabolicFormula', opt.value)}
            style={[
              styles.formulaChoice,
              {
                backgroundColor: colors.surfaceRaised,
                borderColor: selected
                  ? colors.accent
                  : measurementErrors.metabolicFormula
                    ? colors.coral
                    : colors.separator,
              },
            ]}
          >
            <Text
              style={[
                styles.formulaChoiceLabel,
                { color: selected ? colors.accentText : colors.text },
              ]}
            >
              {opt.label}
            </Text>
            <Text style={[styles.formulaChoiceDesc, { color: colors.textMuted }]}>
              {opt.description}
            </Text>
          </Pressable>
        );
      })}
      {measurementErrors.metabolicFormula && (
        <FieldError message={measurementErrors.metabolicFormula} colors={colors} />
      )}

      {saveError && (
        <Text
          accessibilityRole="alert"
          style={[styles.saveError, { color: colors.coral }]}
          testID="save-error"
        >
          {saveError}
        </Text>
      )}

      <Button
        label={saving ? 'Saving…' : 'Continue'}
        onPress={onContinue}
        disabled={saving}
        style={styles.primaryAction}
        accessibilityLabel={saving ? 'Saving your measurements' : 'Continue to your target'}
        accessibilityHint="Saves your profile and reveals your daily calorie target"
      />
    </StepContainer>
  );
}
