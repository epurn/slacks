/**
 * Shared visual-review settled-marker helper (FTY-270).
 *
 * FTY-247's `VisualReviewSettleOverlay` renders the `visual-review-settled:
 * <preset>` marker as a sibling of the navigator Stack, which is unreachable
 * while a sub-state is presented as a React Native `<Modal
 * accessibilityViewIsModal>`: on iOS that flag isolates the modal's own
 * accessibility subtree from everything outside it, so the shared sibling
 * marker is invisible to Maestro/XCUITest for as long as the modal is up
 * (FTY-262's evidence). A modal-based seam must instead mount its own marker
 * *inside* the modal's subtree.
 *
 * This component is the single reusable source of that marker so a per-screen
 * seam (FTY-262..268) never has to redefine the testID, the invisible/
 * non-interactive styling, or the network-quiet settle-timing rule. Mount it
 * anywhere inside the modal's own tree:
 *
 * ```tsx
 * import { VisualReviewSettleMarker } from '@/e2e/visualReview';
 *
 * <Modal accessibilityViewIsModal visible={visible}>
 *   {...sheet content...}
 *   <VisualReviewSettleMarker preset={activePresetName} />
 * </Modal>
 * ```
 *
 * `VisualReviewSettleOverlay` itself is built on this same component (passed
 * the navigator-reachable preset name) so there is one marker source of truth
 * for both the non-modal and the modal case.
 */

import { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { isE2EMode } from '../launchMode';
import { useVisualReviewFetchTick } from './hooks';

/**
 * How long the target must be network-quiet before the marker appears. The
 * E2E mock resolves synchronously, so the initial burst of fixture reads
 * completes in a few ms; this window closes once React has committed the
 * loaded state. Each new mock request restarts it.
 */
export const QUIET_MS = 400;

export interface VisualReviewSettleMarkerProps {
  /**
   * The preset name this marker represents while it is the active,
   * on-screen one, or `null`/`undefined` when this seam's preset is not the
   * active one (renders nothing). Switching to a different preset name hides
   * the marker until the new name's own settle window elapses.
   */
  preset: string | null | undefined;
  /**
   * An extra readiness gate beyond the shared network-quiet timer, for a
   * sub-state whose own async data must also be loaded before the state is
   * truly settled (e.g. a modal's search results or a pre-seeded draft).
   * Defaults to `true` (no extra gate). The marker appears only once BOTH the
   * network-quiet window and this are satisfied.
   */
  ready?: boolean;
}

/**
 * Renders the canonical `visual-review-settled:<preset>` marker once `preset`
 * has been the stable, active one for {@link QUIET_MS} with no new mock
 * request, and `ready` (if supplied) is true. Renders nothing outside E2E mode,
 * before settle, or when `preset` is `null`/`undefined` — inert on every real
 * launch and in release builds.
 */
export function VisualReviewSettleMarker({
  preset,
  ready = true,
}: VisualReviewSettleMarkerProps): React.ReactElement | null {
  const fetchTick = useVisualReviewFetchTick();
  // The preset name we've settled *for*. Tracking the name (rather than a
  // plain boolean) means switching to a different preset hides the marker
  // until the new one settles, without a synchronous reset-to-false inside
  // the effect.
  const [settledFor, setSettledFor] = useState<string | null>(null);

  const armed = isE2EMode() && !!preset;

  useEffect(() => {
    if (!armed || !preset) return;
    const name = preset;
    // Arm the network-quiet timer. A new mock request changes fetchTick,
    // re-running this effect and restarting the window; setState happens only
    // in the async callback, never synchronously in the effect body.
    const timer = setTimeout(() => setSettledFor(name), QUIET_MS);
    return () => clearTimeout(timer);
  }, [armed, preset, fetchTick]);

  if (!armed || !ready || settledFor !== preset) return null;

  const marker = `visual-review-settled:${preset}`;
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
  // A small, transparent, non-interactive marker. Absolute so it never shifts
  // layout; `pointerEvents: 'none'` means it never intercepts touches — it only
  // exists for the accessibility tree Maestro reads.
  marker: {
    position: 'absolute',
    top: 96,
    left: 0,
    width: 4,
    height: 4,
  },
});
