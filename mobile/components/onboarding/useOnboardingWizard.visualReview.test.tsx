/**
 * E2E-only initial-state seam tests for the onboarding wizard (FTY-266).
 *
 * Proves the review-focus concerns directly against the hook (no simulated
 * taps):
 * - `onboarding.goal` / `onboarding.measurements_formula` /
 *   `onboarding.target_reveal` each open the wizard on their step with
 *   synthetic step data already in place, while a visual-review preset is
 *   active and `isE2EMode()` is true.
 * - The seam is inert outside E2E mode: activating the same preset with
 *   `isE2EMode()` false still opens on step 1 with no reveal, proving the seam
 *   is dead code in a release build.
 * - The default, preset-free boot is unaffected: step 1, no reveal, auto-
 *   detected measurements.
 */

import React from 'react';
import { act, create } from 'react-test-renderer';

let mockE2E = true;
jest.mock('@/e2e/launchMode', () => ({
  isE2EMode: () => mockE2E,
}));

// eslint-disable-next-line import/first
import {
  activateVisualReviewPreset,
  __deactivateVisualReview,
} from '@/e2e/visualReview/session';
// eslint-disable-next-line import/first
import type { SessionRecord } from '@/state/session';
// eslint-disable-next-line import/first
import {
  ONBOARDING_GOAL_PRESET_NAME,
  ONBOARDING_MEASUREMENTS_FORMULA_PRESET_NAME,
  ONBOARDING_TARGET_REVEAL_PRESET_NAME,
} from './visualReviewOnboardingSteps';
// eslint-disable-next-line import/first
import { useOnboardingWizard, type OnboardingWizard } from './useOnboardingWizard';

const SESSION: SessionRecord = {
  serverUrl: 'https://home.example.net',
  token: 'test-token',
  userId: '11111111-1111-1111-1111-111111111111',
};

function Harness({
  onReady,
}: {
  onReady: (wizard: OnboardingWizard) => void;
}) {
  const wizard = useOnboardingWizard({
    session: SESSION,
    detectUnitsFn: () => 'imperial',
    detectTimezoneFn: () => 'Europe/London',
  });
  onReady(wizard);
  return null;
}

function mountWizard(): OnboardingWizard {
  let captured!: OnboardingWizard;
  let tree!: ReturnType<typeof create>;
  act(() => {
    tree = create(<Harness onReady={(w) => (captured = w)} />);
  });
  // Unmount immediately: the wizard snapshot is already captured, and an
  // unmounted harness can't receive an out-of-act state update from a later
  // test's `activateVisualReviewPreset` call (the visual-review core store
  // notifies every subscriber synchronously on activation).
  act(() => {
    tree.unmount();
  });
  return captured;
}

afterEach(() => {
  __deactivateVisualReview();
  mockE2E = true;
});

describe('onboarding.goal seam', () => {
  it('opens on step 1 under E2E mode', () => {
    mockE2E = true;
    activateVisualReviewPreset(ONBOARDING_GOAL_PRESET_NAME, null);
    const wizard = mountWizard();
    expect(wizard.step).toBe(1);
  });
});

describe('onboarding.measurements_formula seam', () => {
  it('opens on step 2 with a prefilled, formula-selected form under E2E mode', () => {
    mockE2E = true;
    activateVisualReviewPreset(ONBOARDING_MEASUREMENTS_FORMULA_PRESET_NAME, null);
    const wizard = mountWizard();
    expect(wizard.step).toBe(2);
    expect(wizard.measurements.metabolicFormula).toBe('mifflin_st_jeor_plus5');
    expect(wizard.measurements.weight).toBe('70');
  });
});

describe('onboarding.target_reveal seam', () => {
  it('opens on step 3 with a synthetic, already-settled reveal under E2E mode', () => {
    mockE2E = true;
    activateVisualReviewPreset(ONBOARDING_TARGET_REVEAL_PRESET_NAME, null);
    const wizard = mountWizard();
    expect(wizard.step).toBe(3);
    expect(wizard.reveal).not.toBeNull();
    expect(wizard.reveal?.target.calories).toBe(2000);
    const opacity = wizard.revealOpacity as unknown as {
      __getValue: () => number;
    };
    expect(opacity.__getValue()).toBe(1);
  });
});

describe('release-build inertness', () => {
  it('ignores the active preset when isE2EMode() is false', () => {
    mockE2E = false;
    activateVisualReviewPreset(ONBOARDING_TARGET_REVEAL_PRESET_NAME, null);
    const wizard = mountWizard();
    expect(wizard.step).toBe(1);
    expect(wizard.reveal).toBeNull();
  });
});

describe('default, preset-free boot', () => {
  it('opens on step 1 with an auto-detected, empty measurements form', () => {
    mockE2E = true;
    const wizard = mountWizard();
    expect(wizard.step).toBe(1);
    expect(wizard.reveal).toBeNull();
    expect(wizard.measurements.metabolicFormula).toBeNull();
    expect(wizard.measurements.unitsPreference).toBe('imperial');
  });
});
