/**
 * Visual-review settled marker (FTY-247).
 *
 * Renders an invisible, non-interactive marker with testID
 * `visual-review-settled:<preset>` once the active preset's state has settled:
 * the target screen is on top (`usePathname()` matches the preset's settledPath)
 * AND the screen has gone network-quiet (no new mock request for
 * {@link QUIET_MS}). Screenshot automation waits on this marker so it captures a
 * fully-loaded, themed screen rather than a mid-load frame.
 *
 * The marker is absolutely positioned at 1×1 with no fill and `pointerEvents:
 * 'none'`, so it never shifts layout or blocks touches — it only exists for the
 * accessibility tree Maestro reads. Renders nothing outside E2E mode or before
 * settle.
 */

import { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { usePathname } from 'expo-router';

import { isE2EMode } from '../launchMode';
import { useVisualReviewCore, useVisualReviewFetchTick } from './hooks';

/**
 * How long the target screen must be network-quiet before the marker appears.
 * The E2E mock resolves synchronously, so the initial burst of fixture reads
 * completes in a few ms; this window closes once React has committed the loaded
 * screen. Each new mock request restarts it.
 */
export const QUIET_MS = 400;

export function VisualReviewSettleOverlay(): React.ReactElement | null {
  const core = useVisualReviewCore();
  const fetchTick = useVisualReviewFetchTick();
  const pathname = usePathname();
  // The preset name we've settled *for*. Tracking the name (rather than a plain
  // boolean) means a preset switch hides the marker until the new state settles,
  // without a synchronous reset-to-false inside the effect.
  const [settledFor, setSettledFor] = useState<string | null>(null);

  // The target screen for the active preset is on top.
  const armed =
    isE2EMode() &&
    core.presetName !== null &&
    core.settledPath !== null &&
    pathname === core.settledPath;

  useEffect(() => {
    if (!armed || !core.presetName) return;
    const name = core.presetName;
    // Arm the network-quiet timer. A new mock request changes fetchTick,
    // re-running this effect and restarting the window; setState happens only in
    // the async callback, never synchronously in the effect body.
    const timer = setTimeout(() => setSettledFor(name), QUIET_MS);
    return () => clearTimeout(timer);
  }, [armed, core.presetName, fetchTick]);

  if (!armed || settledFor !== core.presetName) return null;

  const marker = `visual-review-settled:${core.presetName}`;
  return (
    <View
      testID={marker}
      accessible
      accessibilityLabel={marker}
      pointerEvents="none"
      style={styles.marker}
    />
  );
}

const styles = StyleSheet.create({
  // A small, transparent, non-interactive marker placed clear of the status bar
  // so the accessibility tree exposes it as an on-screen, findable element. It
  // is rendered on top of the navigator (see NavigatorHost) so it is not
  // occluded; `pointerEvents: 'none'` means it never intercepts touches, and the
  // absolute position means it never shifts layout.
  marker: {
    position: 'absolute',
    top: 96,
    left: 0,
    width: 4,
    height: 4,
  },
});
