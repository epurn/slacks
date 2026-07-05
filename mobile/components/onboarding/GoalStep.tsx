/**
 * Onboarding step 1 — goal direction + pace (FTY-103).
 *
 * Extracted from `OnboardingScreen.tsx` (FTY-206). Presentation only: the
 * wizard hook owns the goal state and hands this section the current value and
 * change/continue callbacks.
 */

import { Text } from 'react-native';

import { Button } from '@/components/ui/Button';
import { SegmentedControl, type SegmentedControlOption } from '@/components/ui';
import {
  GAIN_PACE_OPTIONS,
  LOSS_PACE_OPTIONS,
  isGoalStepValid,
  type GoalStepState,
} from '@/state/onboarding';
import type { GoalDirection, PacePreset } from '@/api/goals';

import { SectionLabel, StepContainer, type ThemeColors } from './primitives';
import { styles } from './styles';

const DIRECTION_OPTIONS: readonly SegmentedControlOption<GoalDirection>[] = [
  { value: 'loss', label: 'Lose' },
  { value: 'maintain', label: 'Maintain' },
  { value: 'gain', label: 'Gain' },
];

/**
 * Map a pace preset to a segment that shows the short label and carries the
 * evidence-based description (FTY-222). The shared control renders the selected
 * option's description as a visible caption below the segments — surfacing the
 * copy the hand-rolled per-radio group used to announce only via VoiceOver to
 * every user, while keeping it reachable by VoiceOver as on-screen text.
 */
function paceSegments(
  options: readonly { value: PacePreset; label: string; description: string }[],
): readonly SegmentedControlOption<PacePreset>[] {
  return options.map((o) => ({
    value: o.value,
    label: o.label,
    description: o.description,
  }));
}

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
      <SegmentedControl<GoalDirection>
        testID="goal-direction-segmented-control"
        options={DIRECTION_OPTIONS}
        selected={goalState.direction}
        onSelect={onDirectionChange}
        accessibilityLabel="Goal direction"
      />

      {goalState.direction !== 'maintain' && (
        <>
          <SectionLabel label="Pace" colors={colors} />
          <SegmentedControl<PacePreset>
            testID="goal-pace-segmented-control"
            options={paceSegments(
              goalState.direction === 'loss'
                ? LOSS_PACE_OPTIONS
                : GAIN_PACE_OPTIONS,
            )}
            selected={goalState.pace}
            onSelect={onPaceChange}
            accessibilityLabel="Goal pace"
          />
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
