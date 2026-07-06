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
 * This is the navigator-level (non-modal) instance of the marker: it renders as
 * a sibling of the navigator Stack, which is unreachable while a sub-state is
 * presented as a `<Modal accessibilityViewIsModal>` (see the shared README's
 * "Modal sub-states" section, FTY-270). A modal-based seam mounts
 * {@link VisualReviewSettleMarker} directly inside its own modal subtree
 * instead — this overlay is built on the same helper (passed the
 * navigator-reachable preset name only while it is on the settled path), so
 * there is a single marker source of truth for both cases.
 */

import { usePathname } from 'expo-router';

import { useVisualReviewCore } from './hooks';
import { QUIET_MS, VisualReviewSettleMarker } from './VisualReviewSettleMarker';

export { QUIET_MS };

export function VisualReviewSettleOverlay(): React.ReactElement | null {
  const core = useVisualReviewCore();
  const pathname = usePathname();

  // The target screen for the active preset is on top.
  const onSettledPath =
    core.presetName !== null &&
    core.settledPath !== null &&
    pathname === core.settledPath;

  return <VisualReviewSettleMarker preset={onSettledPath ? core.presetName : null} />;
}
