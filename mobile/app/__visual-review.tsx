/**
 * Visual-review deep-link entry point (FTY-247).
 *
 * Opened by a deep link like:
 *
 *     fatty://__visual-review?preset=today.populated&theme=dark
 *
 * In the E2E debug build this activates the named preset — seeding its synthetic
 * fixtures, forcing the requested theme, and navigating to its screen — so a
 * tester or the FTY-235..241 screenshot tooling can open any named state without
 * a rebuild, a live backend, or manual state-walking.
 *
 * Activation bumps a revision the root layout keys its navigator subtree on, so
 * the target screen mounts fresh with the seeded fixtures in place (rather than
 * showing stale data from a screen mounted before activation). The route runs in
 * two passes: the first activation call bumps the revision (a navigator remount
 * is incoming) and waits; after the remount re-mounts this route with the same
 * params, the now-idempotent call (`changed: false`) performs the navigation —
 * from the route's own reliable in-navigator router context.
 *
 * SECURITY / fail-closed (docs/security/security-baseline.md): the whole flow is
 * gated on `isE2EMode()` — `__DEV__` AND `EXPO_PUBLIC_FATTY_E2E=true`. In a
 * release build `__DEV__` is false, so this route is inert: it neither seeds nor
 * navigates, even if the deep link is opened. An unknown preset name fails closed
 * with a deterministic error marker and never falls through to a real route with
 * partially-seeded state.
 */

import { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';
import { useLocalSearchParams, useRouter, type Href } from 'expo-router';

import { isE2EMode } from '@/e2e/launchMode';
import {
  activateVisualReviewPreset,
  getVisualReviewPreset,
  parseVisualReviewParams,
} from '@/e2e/visualReview';

export default function VisualReviewRoute(): React.ReactElement {
  const rawParams = useLocalSearchParams<{
    preset?: string | string[];
    theme?: string | string[];
  }>();
  const { preset: presetName, theme } = parseVisualReviewParams(rawParams);
  const router = useRouter();

  const e2e = isE2EMode();
  const preset =
    e2e && presetName ? getVisualReviewPreset(presetName) : undefined;

  useEffect(() => {
    if (!e2e || !presetName || !preset) return;
    const { changed } = activateVisualReviewPreset(presetName, theme);
    // The bumping call unmounts this route via the incoming remount; wait for the
    // remounted pass. When activation is idempotent (`changed: false`) we are the
    // post-remount pass — the seeded fixtures are in place, so navigate now.
    if (changed) return;
    if (preset.signedOut) {
      // The remount re-hydrated the session store to a null session for this
      // preset (see e2eSessionStore.load), so the auth gate already routes to
      // sign-in. Nothing to navigate here — and, unlike an imperative signOut,
      // this leaves no sticky state, so a later signed-in preset reseeds cleanly.
      return;
    }
    router.replace(preset.route as Href);
  }, [e2e, presetName, preset, theme, router]);

  // Release / non-E2E build: inert. No seeding, no navigation.
  if (!e2e) {
    return (
      <View
        testID="visual-review-inert"
        accessibilityLabel="visual-review-inert"
        style={styles.hidden}
      />
    );
  }

  // Fail closed on an unknown (or missing) preset with a deterministic marker.
  if (!presetName || !preset) {
    const label = `visual-review-error:unknown-preset:${presetName ?? ''}`;
    return (
      <View
        testID="visual-review-error"
        accessible
        accessibilityLabel={label}
        style={styles.marker}
      />
    );
  }

  // Known preset: activation + navigation take over. The settled marker appears
  // on the target screen once it has loaded.
  return (
    <View
      testID={`visual-review-activating:${presetName}`}
      accessibilityLabel="visual-review-activating"
      style={styles.hidden}
    />
  );
}

const styles = StyleSheet.create({
  hidden: { width: 0, height: 0 },
  marker: { position: 'absolute', top: 96, left: 0, width: 4, height: 4 },
});
