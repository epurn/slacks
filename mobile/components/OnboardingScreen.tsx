/**
 * Goal-led onboarding flow (FTY-103) — three-step wizard:
 *
 *   Step 1 — Goal + pace: direction (lose / maintain / gain) and a pace preset.
 *   Step 2 — Measurements: height, weight, birth year, metabolic-formula
 *             variant. Units and timezone are auto-detected from the device
 *             locale and IANA zone; shown read-only, not asked as a question.
 *   Step 3 — Target reveal: the computed daily calorie target with provenance
 *             ("└ from your goal + your metrics") + continue to Today.
 *
 * This file is the thin wizard shell (FTY-206): it wires the
 * `useOnboardingWizard` hook to the step sections under `components/onboarding/`.
 * The measurements step reuses FTY-021's validation + canonical-unit conversion
 * (`@/state/profile`). The goal and reveal are written via the FTY-106
 * goal-creation endpoint (`@/api/goals`). Everything is built on FTY-097
 * design tokens.
 *
 * Privacy: no profile, goal, or target value is logged at any point.
 */

import { ScrollView } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { createGoal } from '@/api/goals';
import { putProfile } from '@/api/profile';
import { GoalStep } from '@/components/onboarding/GoalStep';
import { MeasurementsStep } from '@/components/onboarding/MeasurementsStep';
import { Stepper } from '@/components/onboarding/primitives';
import { TargetRevealStep } from '@/components/onboarding/TargetRevealStep';
import { useOnboardingWizard } from '@/components/onboarding/useOnboardingWizard';
import type { UnitsPreference } from '@/state/profile';
import type { Session } from '@/state/session';
import { spacing, useTheme } from '@/theme';

// ─────────────────────────────────────────────────────────────────────────────
// Props
// ─────────────────────────────────────────────────────────────────────────────

export interface OnboardingScreenProps {
  /** Authenticated session — onboarding always runs signed-in. */
  session: Session;
  /** Injectable for tests. */
  createGoalFn?: typeof createGoal;
  putProfileFn?: typeof putProfile;
  /** Called when the user completes step 3 → navigate to Today. */
  onComplete: () => void;
  /** Injectable for tests; defaults to Intl-based auto-detection. */
  detectUnitsFn?: () => UnitsPreference;
  detectTimezoneFn?: () => string;
  /** Injectable for profile form validation (current year). */
  currentYearFn?: () => number;
}

// ─────────────────────────────────────────────────────────────────────────────
// Wizard shell
// ─────────────────────────────────────────────────────────────────────────────

export function OnboardingScreen({
  session,
  createGoalFn = createGoal,
  putProfileFn = putProfile,
  onComplete,
  detectUnitsFn,
  detectTimezoneFn,
  currentYearFn,
}: OnboardingScreenProps) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  const wizard = useOnboardingWizard({
    session,
    createGoalFn,
    putProfileFn,
    detectUnitsFn,
    detectTimezoneFn,
    currentYearFn,
  });

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.surface }}
      contentContainerStyle={{
        paddingTop: insets.top + 24,
        paddingBottom: insets.bottom + 32,
        paddingHorizontal: spacing.xl,
      }}
      keyboardShouldPersistTaps="handled"
    >
      <Stepper currentStep={wizard.step} colors={colors} onBack={wizard.handleBack} />

      {wizard.step === 1 && (
        <GoalStep
          goalState={wizard.goalState}
          onDirectionChange={wizard.handleDirectionChange}
          onPaceChange={wizard.handlePaceChange}
          onContinue={wizard.handleContinueFromGoal}
          colors={colors}
        />
      )}

      {wizard.step === 2 && (
        <MeasurementsStep
          measurements={wizard.measurements}
          measurementErrors={wizard.measurementErrors}
          saving={wizard.saving}
          saveError={wizard.saveError}
          isMetric={wizard.isMetric}
          onUpdateMeasurement={wizard.updateMeasurement}
          onContinue={() => void wizard.handleContinueFromMeasurements()}
          colors={colors}
        />
      )}

      {wizard.step === 3 && wizard.reveal && (
        <TargetRevealStep
          reveal={wizard.reveal}
          revealOpacity={wizard.revealOpacity}
          onComplete={onComplete}
          colors={colors}
        />
      )}
    </ScrollView>
  );
}
