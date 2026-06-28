/**
 * Haptic feedback helpers.
 *
 * NOTE: `expo-haptics` is not yet a declared dependency of this package.
 * These functions are intentionally no-ops. To enable real haptic feedback,
 * add `expo-haptics` to mobile/package.json approved_dependencies, install it,
 * and replace the stubs below with:
 *   import * as Haptics from 'expo-haptics';
 *   Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light)
 *
 * All callers respect Reduce Motion by design: haptics are fired only at the
 * few signature beats (entry resolved, correction saved, target reached) — not
 * on every interaction.
 */

/** Light tap — used for item-resolved confirmation. */
export function lightHaptic(): void {
  // stub: add expo-haptics
}

/** Selection-changed feedback — used for chip selection, quick-picks. */
export function selectionHaptic(): void {
  // stub: add expo-haptics
}

/** Success haptic — used when target is reached or correction is saved. */
export function successHaptic(): void {
  // stub: add expo-haptics
}
