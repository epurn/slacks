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
 * The measurements step reuses FTY-021's validation + canonical-unit conversion
 * (`@/state/profile`). The goal and reveal are written via the FTY-106
 * goal-creation endpoint (`@/api/goals`). Everything is built on FTY-097
 * design tokens.
 *
 * Privacy: no profile, goal, or target value is logged at any point.
 */

import {
  useCallback,
  useMemo,
  useState,
} from 'react';
import {
  AccessibilityInfo,
  Animated,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import {
  createGoal,
  GoalsApiError,
  type GoalDirection,
  type GoalTargetResponse,
  type PacePreset,
} from '@/api/goals';
import { putProfile, ProfileApiError } from '@/api/profile';
import { Button } from '@/components/ui/Button';
import {
  DEFAULT_PACE,
  GAIN_PACE_OPTIONS,
  LOSS_PACE_OPTIONS,
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
  METABOLIC_FORMULA_OPTIONS,
  validateProfileForm,
  type ProfileFormErrors,
  type UnitsPreference,
} from '@/state/profile';
import type { Session } from '@/state/session';
import { toApiSession } from '@/state/session';
import {
  radius,
  spacing,
  typeScale,
  useTheme,
} from '@/theme';

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
// Main component
// ─────────────────────────────────────────────────────────────────────────────

export function OnboardingScreen({
  session,
  createGoalFn = createGoal,
  putProfileFn = putProfile,
  onComplete,
  detectUnitsFn = detectUnitsPreference,
  detectTimezoneFn = detectTimezone,
  currentYearFn = () => new Date().getFullYear(),
}: OnboardingScreenProps) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  // ── Step tracking ──────────────────────────────────────────────────────────
  const [step, setStep] = useState<OnboardingStep>(1);

  // ── Step 1 — Goal ──────────────────────────────────────────────────────────
  const [goalState, setGoalState] = useState<GoalStepState>(initialGoalStep);

  // ── Step 2 — Measurements ─────────────────────────────────────────────────
  const detectedUnits = useMemo(() => detectUnitsFn(), [detectUnitsFn]);
  const detectedTimezone = useMemo(() => detectTimezoneFn(), [detectTimezoneFn]);
  const [measurements, setMeasurements] = useState<MeasurementsStepState>(() =>
    initialMeasurementsStep(detectedUnits, detectedTimezone),
  );
  const [measurementErrors, setMeasurementErrors] = useState<ProfileFormErrors>({});

  // ── Step 3 — Target reveal ─────────────────────────────────────────────────
  const [reveal, setReveal] = useState<GoalTargetResponse | null>(null);
  const [revealOpacity] = useState(() => new Animated.Value(0));

  // ── Saving / error state ──────────────────────────────────────────────────
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  // ─────────────────────────────────────────────────────────────────────────
  // Goal step handlers
  // ─────────────────────────────────────────────────────────────────────────

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

  // ─────────────────────────────────────────────────────────────────────────
  // Measurements step handlers
  // ─────────────────────────────────────────────────────────────────────────

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

  // ─────────────────────────────────────────────────────────────────────────
  // Back navigation
  // ─────────────────────────────────────────────────────────────────────────

  const handleBack = useCallback(() => {
    setStep((prev) => (prev > 1 ? ((prev - 1) as OnboardingStep) : prev));
    setSaveError(null);
  }, []);

  // ─────────────────────────────────────────────────────────────────────────
  // Continue — step 1 → 2
  // ─────────────────────────────────────────────────────────────────────────

  const handleContinueFromGoal = useCallback(() => {
    if (!isGoalStepValid(goalState)) return;
    setSaveError(null);
    setStep(2);
  }, [goalState]);

  // ─────────────────────────────────────────────────────────────────────────
  // Continue — step 2 → 3  (saves profile then creates goal → gets reveal)
  // ─────────────────────────────────────────────────────────────────────────

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
  ]);

  // ─────────────────────────────────────────────────────────────────────────
  // Render
  // ─────────────────────────────────────────────────────────────────────────

  const isMetric = measurements.unitsPreference === 'metric';

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
      {/* Stepper */}
      <Stepper currentStep={step} colors={colors} onBack={handleBack} />

      {/* ── Step 1: Goal + pace ─────────────────────────────────────────── */}
      {step === 1 && (
        <StepContainer>
          <Text
            style={[styles.stepTitle, { color: colors.text }]}
            accessibilityRole="header"
          >
            {"What's your goal?"}
          </Text>
          <Text style={[styles.stepSubtitle, { color: colors.textSecondary }]}>
            {"We'll use this to set your daily calorie target."}
          </Text>

          <SectionLabel label="Direction" colors={colors} />
          <Segmented<GoalDirection>
            options={DIRECTION_OPTIONS}
            selected={goalState.direction}
            onSelect={handleDirectionChange}
            accessibilityLabel="Goal direction"
            colors={colors}
          />

          {goalState.direction !== 'maintain' && (
            <>
              <SectionLabel label="Pace" colors={colors} />
              <Segmented<PacePreset>
                options={
                  goalState.direction === 'loss' ? LOSS_PACE_OPTIONS : GAIN_PACE_OPTIONS
                }
                selected={goalState.pace}
                onSelect={handlePaceChange}
                accessibilityLabel="Goal pace"
                colors={colors}
              />
              <Text style={[styles.paceNote, { color: colors.textMuted }]}>
                Steady is evidence-based and preserves lean mass.
              </Text>
            </>
          )}

          <Button
            label="Continue"
            onPress={handleContinueFromGoal}
            disabled={!isGoalStepValid(goalState)}
            style={styles.primaryAction}
            accessibilityLabel="Continue to measurements"
            accessibilityHint="Moves to the body measurements step"
          />
        </StepContainer>
      )}

      {/* ── Step 2: Measurements ────────────────────────────────────────── */}
      {step === 2 && (
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
              onChangeText={(v) => updateMeasurement('heightCm', v)}
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
                  onChangeText={(v) => updateMeasurement('heightFeet', v)}
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
                  onChangeText={(v) => updateMeasurement('heightInches', v)}
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
            onChangeText={(v) => updateMeasurement('weight', v)}
            keyboardType="numeric"
            error={measurementErrors.weight}
            colors={colors}
          />

          {/* Birth year */}
          <LabelledInput
            label="Birth year"
            value={measurements.birthYear}
            onChangeText={(v) => updateMeasurement('birthYear', v)}
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
                onPress={() => updateMeasurement('metabolicFormula', opt.value)}
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
                    { color: selected ? colors.accent : colors.text },
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
            onPress={() => void handleContinueFromMeasurements()}
            disabled={saving}
            style={styles.primaryAction}
            accessibilityLabel={saving ? 'Saving your measurements' : 'Continue to your target'}
            accessibilityHint="Saves your profile and reveals your daily calorie target"
          />
        </StepContainer>
      )}

      {/* ── Step 3: Target reveal ───────────────────────────────────────── */}
      {step === 3 && reveal && (
        <StepContainer>
          <Text
            style={[styles.stepTitle, { color: colors.text }]}
            accessibilityRole="header"
          >
            Your daily target
          </Text>

          {/* Hero calorie number */}
          <Animated.View
            style={[styles.heroContainer, { opacity: revealOpacity }]}
            accessibilityLabel={`Your daily calorie target is ${reveal.target.calories} kilocalories`}
            testID="reveal-hero"
          >
            <Text
              style={[styles.heroNumber, { color: colors.text }]}
              accessibilityElementsHidden
            >
              {reveal.target.calories}
            </Text>
            <Text style={[styles.heroUnit, { color: colors.textSecondary }]}>
              kcal / day
            </Text>

            {/* Provenance line — always visible, per "every number shows where it came from" */}
            <Text
              style={[styles.provenanceLine, { color: colors.textMuted }]}
              accessibilityLabel="Derived from your goal and your body metrics"
              testID="provenance-line"
            >
              └ from your goal + your metrics
            </Text>
          </Animated.View>

          {/* Clamp notice — shown when the backend safety-floored an aggressive plan */}
          {reveal.clamp.clamped && (
            <View
              style={[
                styles.clampCard,
                { backgroundColor: colors.surfaceRaised, borderRadius: radius.md },
              ]}
              accessibilityRole="alert"
              testID="clamp-notice"
            >
              <Text style={[styles.clampTitle, { color: colors.text }]}>
                Target adjusted
              </Text>
              <Text style={[styles.clampBody, { color: colors.textSecondary }]}>
                {"Your requested pace would put the target below the safe minimum, so it's been adjusted upward. You can change your pace in Profile anytime."}
              </Text>
            </View>
          )}

          <Text style={[styles.revealNote, { color: colors.textSecondary }]}>
            This is your starting target. It updates as your metrics change.
          </Text>

          <Button
            label="Get started"
            onPress={onComplete}
            style={styles.primaryAction}
            accessibilityLabel="Get started — go to Today"
            accessibilityHint="Opens the Today screen with your calorie target"
            testID="continue-button"
          />
        </StepContainer>
      )}
    </ScrollView>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Error message helper
// ─────────────────────────────────────────────────────────────────────────────

function errorMessage(err: unknown): string {
  if (err instanceof GoalsApiError || err instanceof ProfileApiError) {
    return err.message;
  }
  return 'Could not save. Check your connection and try again.';
}

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────

const DIRECTION_OPTIONS: readonly { value: GoalDirection; label: string }[] = [
  { value: 'loss', label: 'Lose' },
  { value: 'maintain', label: 'Maintain' },
  { value: 'gain', label: 'Gain' },
];

// ─────────────────────────────────────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────────────────────────────────────

function StepContainer({ children }: { children: React.ReactNode }) {
  return <View style={styles.stepContainer}>{children}</View>;
}

function Stepper({
  currentStep,
  colors,
  onBack,
}: {
  currentStep: OnboardingStep;
  colors: ReturnType<typeof useTheme>['colors'];
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

function SectionLabel({
  label,
  colors,
}: {
  label: string;
  colors: ReturnType<typeof useTheme>['colors'];
}) {
  return (
    <Text style={[styles.sectionLabel, { color: colors.textMuted }]}>{label}</Text>
  );
}

function LabelledInput({
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
  colors: ReturnType<typeof useTheme>['colors'];
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

function FieldError({
  message,
  colors,
}: {
  message: string;
  colors: ReturnType<typeof useTheme>['colors'];
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

function Segmented<T extends string>({
  options,
  selected,
  onSelect,
  accessibilityLabel,
  colors,
}: {
  options: readonly { value: T; label: string; description?: string }[];
  selected: T;
  onSelect: (v: T) => void;
  accessibilityLabel: string;
  colors: ReturnType<typeof useTheme>['colors'];
}) {
  return (
    <View
      accessibilityRole="radiogroup"
      accessibilityLabel={accessibilityLabel}
      style={[styles.segmented, { backgroundColor: colors.controlBackground }]}
    >
      {options.map((opt) => {
        const isSelected = opt.value === selected;
        return (
          <Pressable
            key={opt.value}
            accessibilityRole="radio"
            accessibilityState={{ selected: isSelected }}
            accessibilityLabel={
              opt.description ? `${opt.label}: ${opt.description}` : opt.label
            }
            onPress={() => onSelect(opt.value)}
            style={[
              styles.segment,
              isSelected && { backgroundColor: colors.surfaceRaised },
            ]}
          >
            <Text
              style={[
                styles.segmentLabel,
                {
                  color: isSelected ? colors.text : colors.textSecondary,
                  fontWeight: isSelected ? '600' : '400',
                },
              ]}
            >
              {opt.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Styles
// ─────────────────────────────────────────────────────────────────────────────

const styles = StyleSheet.create({
  stepContainer: {
    flex: 1,
    paddingTop: spacing.xl,
  },
  stepperRow: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  backButton: {
    minHeight: 44,
    minWidth: 60,
    justifyContent: 'center',
  },
  backButtonLabel: {
    fontSize: typeScale.body,
    fontWeight: '500',
  },
  backButtonPlaceholder: {
    minWidth: 60,
  },
  dotsContainer: {
    flexDirection: 'row',
    gap: spacing.xs,
    alignItems: 'center',
    justifyContent: 'center',
  },
  dot: {
    height: 8,
    borderRadius: radius.full,
  },
  stepTitle: {
    fontSize: typeScale.largeTitle,
    fontWeight: '700',
    letterSpacing: -0.5,
    marginBottom: spacing.sm,
  },
  stepSubtitle: {
    fontSize: typeScale.body,
    marginBottom: spacing.xl,
    lineHeight: 22,
  },
  sectionLabel: {
    fontSize: typeScale.footnote,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginTop: spacing.lg,
    marginBottom: spacing.xs,
  },
  segmented: {
    flexDirection: 'row',
    borderRadius: radius.md,
    padding: 2,
    gap: 2,
  },
  segment: {
    flex: 1,
    paddingVertical: spacing.sm,
    borderRadius: radius.sm,
    alignItems: 'center',
    minHeight: 44,
    justifyContent: 'center',
  },
  segmentLabel: {
    fontSize: typeScale.footnote,
  },
  paceNote: {
    fontSize: typeScale.footnote,
    marginTop: spacing.sm,
    textAlign: 'center',
  },
  autoDetectRow: {
    padding: spacing.md,
    marginBottom: spacing.lg,
    gap: spacing.xs,
  },
  autoDetectLabel: {
    fontSize: typeScale.footnote,
    fontWeight: '500',
  },
  autoDetectNote: {
    fontSize: typeScale.caption1,
    marginTop: spacing.xs,
  },
  fieldGroup: {
    marginTop: spacing.md,
  },
  fieldLabel: {
    fontSize: typeScale.footnote,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.5,
    marginBottom: spacing.xs,
  },
  textInput: {
    borderWidth: 1,
    borderRadius: radius.sm,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.md,
    fontSize: typeScale.body,
    minHeight: 44,
  },
  fieldError: {
    fontSize: typeScale.footnote,
    marginTop: spacing.xs,
  },
  imperialHeightRow: {
    flexDirection: 'row',
    gap: spacing.sm,
  },
  imperialHeightInput: {
    flex: 1,
  },
  formulaNote: {
    fontSize: typeScale.footnote,
    marginBottom: spacing.sm,
    lineHeight: 18,
  },
  formulaChoice: {
    borderWidth: 1,
    borderRadius: radius.sm,
    padding: spacing.md,
    marginBottom: spacing.xs,
    minHeight: 60,
    justifyContent: 'center',
  },
  formulaChoiceLabel: {
    fontSize: typeScale.subhead,
    fontWeight: '600',
  },
  formulaChoiceDesc: {
    fontSize: typeScale.footnote,
    marginTop: 2,
  },
  saveError: {
    fontSize: typeScale.footnote,
    marginTop: spacing.md,
    textAlign: 'center',
  },
  primaryAction: {
    marginTop: spacing.xxl,
  },
  // Step 3 — Target reveal
  heroContainer: {
    alignItems: 'center',
    paddingVertical: spacing.xxxl,
  },
  heroNumber: {
    fontSize: typeScale.heroDisplay,
    fontWeight: '700',
    letterSpacing: -1,
    fontVariant: ['tabular-nums'],
  },
  heroUnit: {
    fontSize: typeScale.title3,
    marginTop: spacing.xs,
  },
  provenanceLine: {
    fontSize: typeScale.footnote,
    marginTop: spacing.sm,
  },
  clampCard: {
    padding: spacing.md,
    marginBottom: spacing.lg,
  },
  clampTitle: {
    fontSize: typeScale.subhead,
    fontWeight: '600',
    marginBottom: spacing.xs,
  },
  clampBody: {
    fontSize: typeScale.footnote,
    lineHeight: 18,
  },
  revealNote: {
    fontSize: typeScale.footnote,
    textAlign: 'center',
    marginBottom: spacing.md,
  },
});
