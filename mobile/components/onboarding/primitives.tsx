/**
 * Reusable form primitives for the goal-led onboarding flow (FTY-103).
 *
 * Extracted from `OnboardingScreen.tsx` (FTY-206). These are the small,
 * presentation-only building blocks the step sections compose from:
 * `StepContainer`, `Stepper`, `SectionLabel`, `LabelledInput`, and
 * `FieldError`. (Goal Direction/Pace now use the shared native
 * `components/ui/SegmentedControl` — FTY-222 — not a local pill group.)
 */

import type { ReactNode } from 'react';
import { Pressable, Text, TextInput, View } from 'react-native';

import { useTheme } from '@/theme';

import { styles } from './styles';

/** Theme palette shared by every onboarding primitive and step section. */
export type ThemeColors = ReturnType<typeof useTheme>['colors'];

export function StepContainer({ children }: { children: ReactNode }) {
  return <View style={styles.stepContainer}>{children}</View>;
}

export function Stepper({
  currentStep,
  colors,
  onBack,
}: {
  currentStep: number;
  colors: ThemeColors;
  onBack: () => void;
}) {
  const totalSteps = 3;
  return (
    <View style={styles.stepperRow}>
      {currentStep > 1 ? (
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Back"
          accessibilityHint="Go back to the previous step"
          onPress={onBack}
          style={styles.backButton}
          testID="back-button"
        >
          <Text style={[styles.backButtonLabel, { color: colors.textSecondary }]}>
            ‹ Back
          </Text>
        </Pressable>
      ) : (
        <View style={styles.backButtonPlaceholder} />
      )}

      <View
        style={styles.dotsContainer}
        accessibilityRole="progressbar"
        accessibilityLabel={`Step ${currentStep} of ${totalSteps}`}
        accessibilityValue={{ now: currentStep, min: 1, max: totalSteps }}
      >
        {Array.from({ length: totalSteps }, (_, i) => {
          const active = i + 1 === currentStep;
          const done = i + 1 < currentStep;
          return (
            <View
              key={i}
              accessibilityElementsHidden
              style={[
                styles.dot,
                {
                  backgroundColor:
                    active || done ? colors.accent : colors.separator,
                  width: active ? 20 : 8,
                },
              ]}
            />
          );
        })}
      </View>

      <View style={styles.backButtonPlaceholder} />
    </View>
  );
}

export function SectionLabel({
  label,
  colors,
}: {
  label: string;
  colors: ThemeColors;
}) {
  return (
    <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>{label}</Text>
  );
}

export function LabelledInput({
  label,
  value,
  onChangeText,
  keyboardType = 'default',
  placeholder,
  error,
  colors,
}: {
  label: string;
  value: string;
  onChangeText: (v: string) => void;
  keyboardType?: 'default' | 'numeric' | 'number-pad';
  placeholder?: string;
  error?: string;
  colors: ThemeColors;
}) {
  return (
    <View style={styles.fieldGroup}>
      <Text style={[styles.fieldLabel, { color: colors.textSecondary }]}>{label}</Text>
      <TextInput
        accessibilityLabel={label}
        value={value}
        onChangeText={onChangeText}
        keyboardType={keyboardType}
        inputMode={keyboardType === 'numeric' ? 'numeric' : 'text'}
        placeholder={placeholder}
        placeholderTextColor={colors.textMuted}
        style={[
          styles.textInput,
          {
            backgroundColor: colors.surfaceRaised,
            color: colors.text,
            borderColor: error ? colors.coral : colors.separator,
          },
        ]}
      />
      {error && <FieldError message={error} colors={colors} />}
    </View>
  );
}

export function FieldError({
  message,
  colors,
}: {
  message: string;
  colors: ThemeColors;
}) {
  return (
    <Text
      accessibilityRole="alert"
      style={[styles.fieldError, { color: colors.coral }]}
    >
      {message}
    </Text>
  );
}

