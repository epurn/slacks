/**
 * Visual-review sub-state seam — onboarding wizard steps (FTY-266).
 *
 * The onboarding wizard's `step` (`useOnboardingWizard.ts`) is component-local
 * `useState`, and the E2E launch harness marks onboarding complete for the
 * synthetic user at boot (`setupE2EMode()` in `e2e/launchMode.ts`), so the
 * wizard is never even shown by default — FTY-247 left it out of its in-scope
 * manifest for exactly this reason (see its README's "Deferred sub-state
 * presets"). This module is the onboarding-owned plug-in the join contract
 * expects: it registers three sub-state presets — one per wizard step —
 * through {@link registerVisualReviewPreset} (never editing the shared
 * registry or manifest), and exports the small, pure predicates/seeds the auth
 * gate (`app/_layout.tsx`) and `useOnboardingWizard` read to reach each step
 * directly, with no simulated taps.
 *
 * All fixture data is synthetic — no real user, body, or goal data.
 */

import type { GoalTargetResponse } from '@/api/goals';
import { registerVisualReviewPreset } from '@/e2e/visualReview';
import type { MeasurementsStepState, OnboardingStep } from '@/state/onboarding';

/** Deep-link preset name for the wizard's step 1 (goal + pace). */
export const ONBOARDING_GOAL_PRESET_NAME = 'onboarding.goal';
/** Deep-link preset name for the wizard's step 2 (measurements + formula). */
export const ONBOARDING_MEASUREMENTS_FORMULA_PRESET_NAME =
  'onboarding.measurements_formula';
/** Deep-link preset name for the wizard's step 3 (target reveal). */
export const ONBOARDING_TARGET_REVEAL_PRESET_NAME = 'onboarding.target_reveal';

/** The wizard step each onboarding preset opens on. */
const STEP_BY_PRESET: Readonly<Record<string, OnboardingStep>> = {
  [ONBOARDING_GOAL_PRESET_NAME]: 1,
  [ONBOARDING_MEASUREMENTS_FORMULA_PRESET_NAME]: 2,
  [ONBOARDING_TARGET_REVEAL_PRESET_NAME]: 3,
};

/**
 * The E2E-only initial step for the given active visual-review preset, or
 * `null` when it names none of the three onboarding presets (every other
 * preset, and the preset-free default).
 */
export function onboardingSeamInitialStep(
  presetName: string | null,
): OnboardingStep | null {
  if (presetName === null) return null;
  return STEP_BY_PRESET[presetName] ?? null;
}

/**
 * Forces the auth gate's onboarding status to `incomplete` while one of the
 * three onboarding presets is active — overriding the E2E harness's boot-time
 * `markOnboardingComplete` seed (the "skip the onboarding-complete seed"
 * coordination the join contract needs) so the wizard actually renders instead
 * of the gate routing straight to Today. `null` for every other preset and the
 * preset-free default, so the normal E2E flows are unaffected.
 */
export function onboardingStatusOverrideForVisualReview(
  presetName: string | null,
): 'incomplete' | null {
  return presetName !== null && presetName in STEP_BY_PRESET
    ? 'incomplete'
    : null;
}

/**
 * Synthetic, prefilled measurements for `onboarding.measurements_formula` — a
 * completed form with a metabolic-formula variant already selected, so the
 * audit sees the selected-chip state rather than a blank form.
 */
export const ONBOARDING_MEASUREMENTS_SEED: MeasurementsStepState = {
  unitsPreference: 'metric',
  heightCm: '175',
  heightFeet: '',
  heightInches: '',
  weight: '70',
  birthYear: '1990',
  metabolicFormula: 'mifflin_st_jeor_plus5',
  timezone: 'UTC',
};

/**
 * Synthetic target reveal for `onboarding.target_reveal`, shaped like the real
 * `POST /goal` response (mirrors `E2E_GOAL_TARGET_RESPONSE` in `e2e/fixtures.ts`).
 */
export const ONBOARDING_TARGET_REVEAL_SEED: GoalTargetResponse = {
  goal: {
    id: 'e2e-onboarding-goal-00000000-0000-0000-0000-000000000000',
    user_id: 'e2e-onboarding-user-00000000-0000-0000-0000-000000000000',
    start_weight_kg: 75,
    start_date: '2026-01-01',
    target_weight_kg: 72,
    target_date: '2026-04-01',
    is_active: true,
  },
  target: {
    calories: 2000,
    rmr_kcal: 1600,
    tdee_kcal: 2100,
    direction: 'loss',
    clamped: false,
  },
  provenance: { source: 'derived', basis: 'goal_and_metrics' },
  clamp: { clamped: false, reason: null },
};

// Register the three onboarding-owned sub-state presets. Registration runs
// unconditionally at module load (mirroring `presets.ts`) — cheap, and inert
// on its own: reachable only through the `isE2EMode()`-gated deep-link route
// and the `isE2EMode()` checks the wizard and auth gate apply before reading
// any of this.
registerVisualReviewPreset({
  name: ONBOARDING_GOAL_PRESET_NAME,
  route: '/onboarding',
  settledPath: '/onboarding',
});
registerVisualReviewPreset({
  name: ONBOARDING_MEASUREMENTS_FORMULA_PRESET_NAME,
  route: '/onboarding',
  settledPath: '/onboarding',
});
registerVisualReviewPreset({
  name: ONBOARDING_TARGET_REVEAL_PRESET_NAME,
  route: '/onboarding',
  settledPath: '/onboarding',
});
