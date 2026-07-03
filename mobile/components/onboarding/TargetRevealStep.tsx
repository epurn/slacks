/**
 * Onboarding step 3 — target reveal (FTY-103).
 *
 * Extracted from `OnboardingScreen.tsx` (FTY-206). Presentation only: the
 * wizard hook computes the target reveal and drives the fade-in; this section
 * renders the hero calorie number with its always-visible provenance line, the
 * calm clamp notice when the backend safety-floored the plan, and "Get started".
 */

import { Animated, Text, View } from 'react-native';

import { Button } from '@/components/ui/Button';
import type { GoalTargetResponse } from '@/api/goals';
import { radius } from '@/theme';

import { StepContainer, type ThemeColors } from './primitives';
import { styles } from './styles';

export function TargetRevealStep({
  reveal,
  revealOpacity,
  onComplete,
  colors,
}: {
  reveal: GoalTargetResponse;
  revealOpacity: Animated.Value;
  onComplete: () => void;
  colors: ThemeColors;
}) {
  return (
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
  );
}
