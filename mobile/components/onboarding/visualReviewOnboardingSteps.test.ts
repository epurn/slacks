/**
 * Onboarding visual-review seam tests (FTY-266).
 *
 * Proves the three onboarding sub-state presets are registered through the
 * FTY-247 registration API (never editing its registry), and that the pure
 * step/status predicates the auth gate and the wizard hook read resolve
 * correctly for each preset and fall through to `null` for everything else.
 */

// Importing the module registers the three onboarding presets as a side effect.
import {
  ONBOARDING_GOAL_PRESET_NAME,
  ONBOARDING_MEASUREMENTS_FORMULA_PRESET_NAME,
  ONBOARDING_MEASUREMENTS_SEED,
  ONBOARDING_TARGET_REVEAL_PRESET_NAME,
  ONBOARDING_TARGET_REVEAL_SEED,
  onboardingSeamInitialStep,
  onboardingStatusOverrideForVisualReview,
} from './visualReviewOnboardingSteps';
import { getVisualReviewPreset } from '@/e2e/visualReview';

describe('onboarding preset registration', () => {
  it('registers all three onboarding presets on the shared registry', () => {
    for (const name of [
      ONBOARDING_GOAL_PRESET_NAME,
      ONBOARDING_MEASUREMENTS_FORMULA_PRESET_NAME,
      ONBOARDING_TARGET_REVEAL_PRESET_NAME,
    ]) {
      const preset = getVisualReviewPreset(name);
      expect(preset).toBeDefined();
      expect(preset?.route).toBe('/onboarding');
      expect(preset?.settledPath).toBe('/onboarding');
    }
  });
});

describe('onboardingSeamInitialStep', () => {
  it('maps each onboarding preset to its wizard step', () => {
    expect(onboardingSeamInitialStep(ONBOARDING_GOAL_PRESET_NAME)).toBe(1);
    expect(
      onboardingSeamInitialStep(ONBOARDING_MEASUREMENTS_FORMULA_PRESET_NAME),
    ).toBe(2);
    expect(onboardingSeamInitialStep(ONBOARDING_TARGET_REVEAL_PRESET_NAME)).toBe(
      3,
    );
  });

  it('returns null for an unrelated preset and for no active preset', () => {
    expect(onboardingSeamInitialStep('today.populated')).toBeNull();
    expect(onboardingSeamInitialStep(null)).toBeNull();
  });
});

describe('onboardingStatusOverrideForVisualReview', () => {
  it('forces incomplete while an onboarding preset is active', () => {
    expect(
      onboardingStatusOverrideForVisualReview(ONBOARDING_GOAL_PRESET_NAME),
    ).toBe('incomplete');
    expect(
      onboardingStatusOverrideForVisualReview(
        ONBOARDING_MEASUREMENTS_FORMULA_PRESET_NAME,
      ),
    ).toBe('incomplete');
    expect(
      onboardingStatusOverrideForVisualReview(ONBOARDING_TARGET_REVEAL_PRESET_NAME),
    ).toBe('incomplete');
  });

  it('is null for an unrelated preset and for no active preset', () => {
    expect(onboardingStatusOverrideForVisualReview('today.populated')).toBeNull();
    expect(onboardingStatusOverrideForVisualReview(null)).toBeNull();
  });
});

describe('synthetic seeds', () => {
  it('measurements seed carries a concrete metabolic formula', () => {
    expect(ONBOARDING_MEASUREMENTS_SEED.metabolicFormula).toBe(
      'mifflin_st_jeor_plus5',
    );
  });

  it('target reveal seed is not clamped and carries a positive calorie target', () => {
    expect(ONBOARDING_TARGET_REVEAL_SEED.clamp.clamped).toBe(false);
    expect(ONBOARDING_TARGET_REVEAL_SEED.target.calories).toBeGreaterThan(0);
  });
});
