/**
 * Visual-review mode barrel (FTY-247).
 *
 * Importing this module registers the in-scope preset manifest (the side-effect
 * `import './presets'`) and re-exports the public surface the root wiring and the
 * deep-link route consume. The per-screen seam stories (FTY-262..268) import
 * `registerVisualReviewPreset` from here to plug in their sub-state presets
 * without editing the registry or the manifest.
 *
 * Everything here is gated behind `isE2EMode()` at its call sites; release builds
 * dead-code-eliminate the activation paths.
 */

import './presets';

export {
  registerVisualReviewPreset,
  getVisualReviewPreset,
  listVisualReviewPresetNames,
  parseVisualReviewParams,
  type VisualReviewParams,
} from './registry';
export type {
  VisualReviewPreset,
  VisualReviewResponse,
  VisualReviewFetchContext,
} from './types';
export {
  activateVisualReviewPreset,
  resolveVisualReviewFetch,
  recordVisualReviewServed,
} from './session';
export {
  useVisualReviewRevision,
  useVisualReviewCore,
  useVisualReviewTheme,
} from './hooks';
export { VisualReviewSettleOverlay } from './VisualReviewSettleOverlay';
