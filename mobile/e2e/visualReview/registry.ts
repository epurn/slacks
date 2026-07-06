/**
 * Visual-review preset registry + deep-link parsing (FTY-247).
 *
 * This module owns the registration API and the parsing of the visual-review
 * deep link. It is the **join contract** between this story and the per-screen
 * seam stories (FTY-262..268): a screen-owned module registers a sub-state
 * preset by calling {@link registerVisualReviewPreset} from its own lane,
 * **without editing this file or `presets.ts`**. The registry, route parsing,
 * theme handling, settled-marker convention, and fail-closed lookup all live
 * here; per-screen presets merely plug in.
 *
 * The registry is a plain in-memory map. It carries no secrets and no auth
 * state; it only becomes reachable behind the `isE2EMode()` gate (see
 * `../launchMode.ts`), which release builds dead-code-eliminate.
 */

import type { VisualReviewPreset } from './types';

/** Registered presets, keyed by their dotted name. */
const registry = new Map<string, VisualReviewPreset>();

/**
 * Register a visual-review preset. Idempotent per name: a later registration
 * replaces an earlier one, which lets a seam story override a placeholder. This
 * is the API FTY-262..268 call from their own modules to contribute a sub-state
 * preset without touching the shared registry or manifest.
 *
 * @throws if the preset name is empty (a programming error, surfaced loudly in
 *   the dev build rather than silently registering an unreachable preset).
 */
export function registerVisualReviewPreset(preset: VisualReviewPreset): void {
  if (!preset.name) {
    throw new Error('registerVisualReviewPreset: preset.name is required');
  }
  registry.set(preset.name, preset);
}

/** Look up a registered preset by name, or `undefined` when none is registered. */
export function getVisualReviewPreset(
  name: string,
): VisualReviewPreset | undefined {
  return registry.get(name);
}

/** All registered preset names, sorted for stable docs/tests. */
export function listVisualReviewPresetNames(): string[] {
  return [...registry.keys()].sort();
}

/**
 * Test-only: drop all registrations. Not exported from the barrel; used by unit
 * tests to isolate registration behaviour from the shipped preset manifest.
 */
export function __resetVisualReviewRegistry(): void {
  registry.clear();
}

/** The parsed, validated visual-review deep-link parameters. */
export interface VisualReviewParams {
  /** The requested preset name, or `null` when absent/blank. */
  readonly preset: string | null;
  /** The forced theme, or `null` when absent or not a valid value. */
  readonly theme: 'light' | 'dark' | null;
}

/** Read the first value of an Expo Router param that may arrive as a string or array. */
function firstParam(value: string | string[] | undefined): string | undefined {
  if (Array.isArray(value)) return value[0];
  return value;
}

/**
 * Parse the `preset` and `theme` query params from a visual-review deep link.
 * `theme` is accepted only when it is exactly `light` or `dark`; any other value
 * (including a typo or an injection attempt) is dropped to `null`, so the preset
 * falls back to its own default theme rather than an arbitrary override.
 */
export function parseVisualReviewParams(raw: {
  preset?: string | string[];
  theme?: string | string[];
}): VisualReviewParams {
  const presetRaw = firstParam(raw.preset)?.trim();
  const themeRaw = firstParam(raw.theme)?.trim();
  const theme = themeRaw === 'light' || themeRaw === 'dark' ? themeRaw : null;
  return {
    preset: presetRaw && presetRaw.length > 0 ? presetRaw : null,
    theme,
  };
}
