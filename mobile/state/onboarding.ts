/**
 * Pure domain logic for the goal-led onboarding flow (FTY-103).
 *
 * Covers: locale-based auto-detection of units + timezone, the evidence-based
 * pace-preset vocabulary, profile-completeness check, and step-level
 * validation.  All functions are pure (or injected) so they are fully
 * unit-testable without rendering or networking.
 */

import type { GoalDirection, PacePreset } from '@/api/goals';
import type { ProfileDTO } from '@/api/profile';
import type { MetabolicFormula, UnitsPreference } from '@/state/profile';

// ─────────────────────────────────────────────────────────────────────────────
// Step types
// ─────────────────────────────────────────────────────────────────────────────

export type OnboardingStep = 1 | 2 | 3;

// ─────────────────────────────────────────────────────────────────────────────
// Locale auto-detection
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Detect whether the device uses imperial or metric units from the device
 * locale (via Intl). Only three countries use imperial for body measurements:
 * the US, Liberia, and Myanmar. Everything else is metric.
 *
 * Injectable (`intl`) for tests so the system Intl is not required.
 */
export function detectUnitsPreference(
  intl: typeof Intl = Intl,
): UnitsPreference {
  try {
    const locale = intl.DateTimeFormat().resolvedOptions().locale;
    // Region subtag is the last two-letter segment, e.g. "en-US" → "US"
    const region = locale.split('-').pop()?.toUpperCase() ?? '';
    return region === 'US' || region === 'LR' || region === 'MM'
      ? 'imperial'
      : 'metric';
  } catch {
    return 'metric';
  }
}

/**
 * Detect the device IANA timezone from Intl.DateTimeFormat.
 * Falls back to 'UTC' if unavailable.
 */
export function detectTimezone(intl: typeof Intl = Intl): string {
  try {
    return intl.DateTimeFormat().resolvedOptions().timeZone ?? 'UTC';
  } catch {
    return 'UTC';
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Evidence-based pace presets
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Evidence-based pace preset for the given goal direction.
 *
 * Loss presets are grounded in the ~0.5–1% bodyweight/wk safe rate
 * (NIH/NIDDK); we cap the offered range so no default exceeds ~1%/wk.
 * Gain presets are gentler (lean gain is far slower: ~0.1–0.25%/wk).
 * Maintain has no pace control.
 */
export interface PaceOption {
  readonly value: PacePreset;
  readonly label: string;
  readonly description: string;
}

export const LOSS_PACE_OPTIONS: readonly PaceOption[] = [
  {
    value: 'gentle',
    label: 'Gentle',
    description: '~0.25% of bodyweight / week',
  },
  {
    value: 'steady',
    label: 'Steady',
    description: '~0.5% of bodyweight / week — recommended',
  },
  {
    value: 'faster',
    label: 'Faster',
    description: '~0.75–1% of bodyweight / week',
  },
];

export const GAIN_PACE_OPTIONS: readonly PaceOption[] = [
  {
    value: 'gentle',
    label: 'Gentle',
    description: '~0.1% of bodyweight / week',
  },
  {
    value: 'steady',
    label: 'Steady',
    description: '~0.25% of bodyweight / week — recommended',
  },
];

/** Default pace for loss and gain goals; matches the evidence-based recommendation. */
export const DEFAULT_PACE: PacePreset = 'steady';

/** Pace options for the given direction; null for maintain (no pace control). */
export function paceOptionsForDirection(
  direction: GoalDirection,
): readonly PaceOption[] | null {
  if (direction === 'maintain') return null;
  return direction === 'loss' ? LOSS_PACE_OPTIONS : GAIN_PACE_OPTIONS;
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 1 — Goal state
// ─────────────────────────────────────────────────────────────────────────────

export interface GoalStepState {
  readonly direction: GoalDirection;
  readonly pace: PacePreset;
}

export function initialGoalStep(): GoalStepState {
  return { direction: 'loss', pace: DEFAULT_PACE };
}

/** True iff the goal step is valid to advance: direction set; pace valid for direction. */
export function isGoalStepValid(state: GoalStepState): boolean {
  if (state.direction === 'maintain') return true;
  const opts = paceOptionsForDirection(state.direction);
  return opts !== null && opts.some((o) => o.value === state.pace);
}

// ─────────────────────────────────────────────────────────────────────────────
// Step 2 — Measurements state
// ─────────────────────────────────────────────────────────────────────────────

/** Measurement form state for onboarding step 2 (mirrors ProfileFormState). */
export interface MeasurementsStepState {
  readonly unitsPreference: UnitsPreference;
  readonly heightCm: string;
  readonly heightFeet: string;
  readonly heightInches: string;
  readonly weight: string;
  readonly birthYear: string;
  readonly metabolicFormula: MetabolicFormula | null;
  readonly timezone: string;
}

/** Seed a blank measurements form from auto-detected locale/timezone. */
export function initialMeasurementsStep(
  unitsPreference: UnitsPreference,
  timezone: string,
): MeasurementsStepState {
  return {
    unitsPreference,
    heightCm: '',
    heightFeet: '',
    heightInches: '',
    weight: '',
    birthYear: '',
    metabolicFormula: null,
    timezone,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// Profile completeness check
// ─────────────────────────────────────────────────────────────────────────────

/**
 * True iff the profile has all the fields the target calculator requires:
 * height, weight, birth year, and a concrete metabolic-formula variant
 * (not the unspecified placeholder).
 */
export function isProfileComplete(profile: ProfileDTO | null): boolean {
  if (!profile) return false;
  const formula = profile.metabolic_formula;
  return (
    profile.height_m !== null &&
    profile.weight_kg !== null &&
    profile.birth_year !== null &&
    (formula === 'mifflin_st_jeor_plus5' ||
      formula === 'mifflin_st_jeor_minus161')
  );
}
