/**
 * Wizard state hook for the goal-led onboarding flow (FTY-103).
 *
 * Owns current-step tracking, the per-step field values, validation, the
 * profile/goal writes, and the calm status-derived error helper. Extracted
 * from `OnboardingScreen.tsx` (FTY-206) so the screen becomes a thin shell that
 * wires this hook to the step sections.
 *
 * Privacy: no profile, goal, or target value is logged at any point.
 */

import { useCallback, useMemo, useState } from 'react';
import { AccessibilityInfo, Animated } from 'react-native';

import {
  createGoal,
  GoalsApiError,
  type GoalDirection,
  type GoalTargetResponse,
  type PacePreset,
} from '@/api/goals';
import { putProfile, ProfileApiError } from '@/api/profile';
import { isE2EMode } from '@/e2e/launchMode';
import { useVisualReviewCore } from '@/e2e/visualReview';
import {
  DEFAULT_PACE,
  detectTimezone,
  detectUnitsPreference,
  initialGoalStep,
  initialMeasurementsStep,
  isGoalStepValid,
  type GoalStepState,
  type MeasurementsStepState,
  type OnboardingStep,
} from '@/state/onboarding';
import {
  validateProfileForm,
  type ProfileFormErrors,
  type UnitsPreference,
} from '@/state/profile';
import { useGoalDirectionController } from '@/state/goalDirection';
import type { Session } from '@/state/session';
import { toApiSession } from '@/state/session';

import {
  ONBOARDING_MEASUREMENTS_FORMULA_PRESET_NAME,
  ONBOARDING_MEASUREMENTS_SEED,
  ONBOARDING_TARGET_REVEAL_PRESET_NAME,
  ONBOARDING_TARGET_REVEAL_SEED,
  onboardingSeamInitialStep,
} from './visualReviewOnboardingSteps';

export interface UseOnboardingWizardParams {
  session: Session;
  createGoalFn?: typeof createGoal;
  putProfileFn?: typeof putProfile;
  detectUnitsFn?: () => UnitsPreference;
  detectTimezoneFn?: () => string;
  currentYearFn?: () => number;
}

export interface OnboardingWizard {
  step: OnboardingStep;
  goalState: GoalStepState;
  measurements: MeasurementsStepState;
  measurementErrors: ProfileFormErrors;
  reveal: GoalTargetResponse | null;
  revealOpacity: Animated.Value;
  saving: boolean;
  saveError: string | null;
  /** True when the detected units are metric (single cm height field). */
  isMetric: boolean;
  handleDirectionChange: (next: GoalDirection) => void;
  handlePaceChange: (next: PacePreset) => void;
  updateMeasurement: <K extends keyof MeasurementsStepState>(
    key: K,
    value: MeasurementsStepState[K],
  ) => void;
  handleBack: () => void;
  handleContinueFromGoal: () => void;
  handleContinueFromMeasurements: () => Promise<void>;
}

/** Map a save failure to a calm, status-derived message — never leak body values. */
export function errorMessage(err: unknown): string {
  if (err instanceof GoalsApiError || err instanceof ProfileApiError) {
    return err.message;
  }
  return 'Could not save. Check your connection and try again.';
}

export function useOnboardingWizard({
  session,
  createGoalFn = createGoal,
  putProfileFn = putProfile,
  detectUnitsFn = detectUnitsPreference,
  detectTimezoneFn = detectTimezone,
  currentYearFn = () => new Date().getFullYear(),
}: UseOnboardingWizardParams): OnboardingWizard {
  const goalDirectionController = useGoalDirectionController();

  // E2E-only initial-state seam (FTY-266): when a visual-review onboarding
  // preset is active — only under `isE2EMode()`, so this is dead in release
  // builds even if the runtime state were somehow non-null — the wizard opens
  // directly on that preset's step with its synthetic step data already in
  // place. No taps are simulated. `null` for every other preset, the
  // preset-free default, and every release build.
  const visualReviewCore = useVisualReviewCore();
  const onboardingSeamPreset = isE2EMode() ? visualReviewCore.presetName : null;
  const seamInitialStep = onboardingSeamInitialStep(onboardingSeamPreset);

  // ── Step tracking ──────────────────────────────────────────────────────────
  const [step, setStep] = useState<OnboardingStep>(() => seamInitialStep ?? 1);

  // ── Step 1 — Goal ──────────────────────────────────────────────────────────
  const [goalState, setGoalState] = useState<GoalStepState>(initialGoalStep);

  // ── Step 2 — Measurements ─────────────────────────────────────────────────
  const detectedUnits = useMemo(() => detectUnitsFn(), [detectUnitsFn]);
  const detectedTimezone = useMemo(() => detectTimezoneFn(), [detectTimezoneFn]);
  const [measurements, setMeasurements] = useState<MeasurementsStepState>(() =>
    onboardingSeamPreset === ONBOARDING_MEASUREMENTS_FORMULA_PRESET_NAME
      ? ONBOARDING_MEASUREMENTS_SEED
      : initialMeasurementsStep(detectedUnits, detectedTimezone),
  );
  const [measurementErrors, setMeasurementErrors] = useState<ProfileFormErrors>({});

  // ── Step 3 — Target reveal ─────────────────────────────────────────────────
  const [reveal, setReveal] = useState<GoalTargetResponse | null>(() =>
    onboardingSeamPreset === ONBOARDING_TARGET_REVEAL_PRESET_NAME
      ? ONBOARDING_TARGET_REVEAL_SEED
      : null,
  );
  // Seeded already-settled (opacity 1, no animation) for the target-reveal
  // preset so the screenshot never needs to wait out the reveal fade.
  const [revealOpacity] = useState(
    () =>
      new Animated.Value(
        onboardingSeamPreset === ONBOARDING_TARGET_REVEAL_PRESET_NAME ? 1 : 0,
      ),
  );

  // ── Saving / error state ──────────────────────────────────────────────────
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // ── Goal step handlers ──────────────────────────────────────────────────────

  const handleDirectionChange = useCallback((next: GoalDirection) => {
    setGoalState((prev) => {
      // 'faster' is a loss-only pace preset; clamp to 'steady' for gain.
      const pace: PacePreset =
        next === 'gain' && prev.pace === 'faster' ? DEFAULT_PACE : prev.pace;
      return { direction: next, pace };
    });
  }, []);

  const handlePaceChange = useCallback((next: PacePreset) => {
    setGoalState((prev) => ({ ...prev, pace: next }));
  }, []);

  // ── Measurements step handlers ──────────────────────────────────────────────

  const updateMeasurement = useCallback(
    <K extends keyof MeasurementsStepState>(
      key: K,
      value: MeasurementsStepState[K],
    ) => {
      setMeasurements((prev) => ({ ...prev, [key]: value }));
      setMeasurementErrors((prev) => {
        const next = { ...prev };
        // Clear the field's error on any change so the user gets immediate feedback.
        if (key === 'heightCm' || key === 'heightFeet' || key === 'heightInches') {
          delete next.height;
        } else if (key === 'weight') {
          delete next.weight;
        } else if (key === 'birthYear') {
          delete next.birthYear;
        } else if (key === 'metabolicFormula') {
          delete next.metabolicFormula;
        }
        return next;
      });
    },
    [],
  );

  // ── Back navigation ─────────────────────────────────────────────────────────

  const handleBack = useCallback(() => {
    setStep((prev) => (prev > 1 ? ((prev - 1) as OnboardingStep) : prev));
    setSaveError(null);
  }, []);

  // ── Continue — step 1 → 2 ────────────────────────────────────────────────────

  const handleContinueFromGoal = useCallback(() => {
    if (!isGoalStepValid(goalState)) return;
    setSaveError(null);
    setStep(2);
  }, [goalState]);

  // ── Continue — step 2 → 3 (saves profile then creates goal → gets reveal) ─────

  const handleContinueFromMeasurements = useCallback(async () => {
    if (!session) return;

    // Validate measurements using the profile form's own validator.
    const currentYear = currentYearFn();
    const validation = validateProfileForm(measurements, currentYear);
    if (!validation.ok) {
      setMeasurementErrors(validation.errors);
      return;
    }

    setSaving(true);
    setSaveError(null);

    try {
      const apiSession = toApiSession(session);

      // 1. Persist the profile (PUT) so the target calculator has the metrics.
      await putProfileFn(apiSession, validation.payload);

      // 2. Create the goal → backend computes + returns the target reveal.
      const goalPayload =
        goalState.direction === 'maintain'
          ? { direction: goalState.direction as GoalDirection }
          : { direction: goalState.direction as GoalDirection, pace: goalState.pace };

      const goalResponse = await createGoalFn(apiSession, goalPayload);

      setReveal(goalResponse);
      goalDirectionController.setGoalDirection(goalResponse.target.direction);

      // Fade in the reveal card.
      revealOpacity.setValue(0);
      const reduced = await AccessibilityInfo.isReduceMotionEnabled();
      if (reduced) {
        revealOpacity.setValue(1);
      } else {
        Animated.timing(revealOpacity, {
          toValue: 1,
          duration: 400,
          useNativeDriver: true,
        }).start();
      }

      setStep(3);
    } catch (err) {
      // Surface a calm, status-derived message — never log the body values.
      setSaveError(errorMessage(err));
    } finally {
      setSaving(false);
    }
  }, [
    session,
    measurements,
    goalState,
    createGoalFn,
    putProfileFn,
    currentYearFn,
    revealOpacity,
    goalDirectionController,
  ]);

  const isMetric = measurements.unitsPreference === 'metric';

  return {
    step,
    goalState,
    measurements,
    measurementErrors,
    reveal,
    revealOpacity,
    saving,
    saveError,
    isMetric,
    handleDirectionChange,
    handlePaceChange,
    updateMeasurement,
    handleBack,
    handleContinueFromGoal,
    handleContinueFromMeasurements,
  };
}
