/**
 * Static Settings copy + option lists (FTY-203, extracted from SettingsScreen).
 *
 * The metabolic-formula copy translates the raw formula keys into the plain,
 * non-jargon labels/descriptions the BODY section and the formula editor show
 * (FTY-190); `settingsFormulaCopy` narrows an untrusted profile value to that
 * copy or `null` when it is an unknown/legacy formula.
 */

import type { ColorSchemeOverride } from '@/theme';
import type { MetabolicFormula } from '@/state/profile';

export const APPEARANCE_OPTIONS: readonly {
  value: ColorSchemeOverride;
  label: string;
}[] = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'System' },
];

const SETTINGS_METABOLIC_FORMULA_COPY: Record<
  MetabolicFormula,
  { readonly label: string; readonly description: string }
> = {
  mifflin_st_jeor_plus5: {
    label: 'Higher calorie baseline',
    description:
      'Uses the Mifflin-St Jeor +5 baseline, giving a slightly higher resting burn estimate.',
  },
  mifflin_st_jeor_minus161: {
    label: 'Lower calorie baseline',
    description:
      'Uses the Mifflin-St Jeor -161 baseline, giving a lower resting burn estimate.',
  },
};

export function settingsFormulaCopy(value?: MetabolicFormula | string | null) {
  if (
    value === 'mifflin_st_jeor_plus5' ||
    value === 'mifflin_st_jeor_minus161'
  ) {
    return SETTINGS_METABOLIC_FORMULA_COPY[value];
  }
  return null;
}
