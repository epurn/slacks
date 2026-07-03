/**
 * Onboarding step 1 — goal direction + pace (FTY-103).
 *
 * Extracted from `OnboardingScreen.tsx` (FTY-206). Presentation only: the
 * wizard hook owns the goal state and hands this section the current value and
 * change/continue callbacks.
 */

import { Text } from 'react-native';

import { Button } from '@/components/ui/Button';
import {
  GAIN_PACE_OPTIONS,
  LOSS_PACE_OPTIONS,
  isGoalStepValid,
  type GoalStepState,
} from '@/state/onboarding';
import type { GoalDirection, PacePreset } from '@/api/goals';

import {
  SectionLabel,
  Segmented,
  StepContainer,
  type ThemeColors,
} from './primitives';
import { styles } from './styles';

const DIRECTION_OPTIONS: readonly { value: GoalDirection; label: string }[] = [
  { value: 'loss', label: 'Lose' },
  { value: 'maintain', label: 'Maintain' },
  { value: 'gain', label: 'Gain' },
];

export function GoalStep({
  goalState,
  onDirectionChange,
  onPaceChange,
  onContinue,
  colors,
}: {
  goalState: GoalStepState;
  onDirectionChange: (next: GoalDirection) => void;
  onPaceChange: (next: PacePreset) => void;
  onContinue: () => void;
  colors: ThemeColors;
}) {
  return (
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
        onSelect={onDirectionChange}
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
            onSelect={onPaceChange}
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
        onPress={onContinue}
        disabled={!isGoalStepValid(goalState)}
        style={styles.primaryAction}
        accessibilityLabel="Continue to measurements"
        accessibilityHint="Moves to the body measurements step"
      />
    </StepContainer>
  );
}
