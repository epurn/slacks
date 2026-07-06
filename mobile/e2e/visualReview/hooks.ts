/**
 * React bindings for the visual-review session (FTY-247).
 *
 * Thin `useSyncExternalStore` wrappers over `session.ts`. Each is a no-op signal
 * outside E2E mode: `useVisualReviewTheme` returns `null` (so the appearance
 * provider ignores it) and the core/fetch channels never emit because nothing
 * activates a preset when `isE2EMode()` is false. Kept separate from the
 * components so non-visual modules (e.g. the appearance provider) can read the
 * theme override without pulling in React Native view code.
 */

import { useSyncExternalStore } from 'react';

import { isE2EMode } from '../launchMode';
import {
  getVisualReviewCore,
  getVisualReviewFetchTick,
  subscribeVisualReviewCore,
  subscribeVisualReviewFetch,
  type VisualReviewCoreSnapshot,
} from './session';

/** The active preset snapshot (or the inert default). */
export function useVisualReviewCore(): VisualReviewCoreSnapshot {
  return useSyncExternalStore(subscribeVisualReviewCore, getVisualReviewCore);
}

/**
 * The remount revision the root layout keys its navigator subtree on. Constant
 * `0` in release builds (nothing ever activates), so the key never changes and
 * the subtree behaves exactly as before.
 */
export function useVisualReviewRevision(): number {
  const core = useVisualReviewCore();
  return core.revision;
}

/**
 * The forced theme for the active preset, or `null`. Returns `null` outside E2E
 * mode so the appearance provider's normal Light/Dark/System preference wins in
 * release builds.
 */
export function useVisualReviewTheme(): 'light' | 'dark' | null {
  const core = useVisualReviewCore();
  return isE2EMode() ? core.theme : null;
}

/** The fetch tick — bumped on every mock request while a preset is active. */
export function useVisualReviewFetchTick(): number {
  return useSyncExternalStore(
    subscribeVisualReviewFetch,
    getVisualReviewFetchTick,
  );
}
