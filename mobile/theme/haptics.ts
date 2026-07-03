import * as Haptics from "expo-haptics";

/**
 * Signature-beat haptics (FTY-181).
 *
 * Fatty is "calm ~95% of the time, branded at the few beats that matter"
 * (docs/design/ux-design.md §5). Identity lives in three designed motion beats,
 * each carrying a matching haptic. This module is the single place those haptics
 * fire so the call sites stay one line and the expo-haptics surface — including
 * its fire-and-forget error handling — lives in one spot.
 *
 * Haptics are best-effort: on a device or simulator without a Taptic Engine the
 * native promise rejects, and a missing haptic must never surface an error into a
 * render or handler path, so every call is fired and its rejection swallowed.
 *
 * Reduce Motion: a haptic is not on-screen motion, so it is *not* suppressed when
 * Reduce Motion is on — only the visual beat degrades to a simple fade (see
 * `theme/motion`). These remain the minimal confirmation the spec keeps under
 * Reduce Motion (docs/design/ux-design.md §7).
 */

/** Fire a haptic without awaiting; swallow rejection (unsupported device, etc.). */
function fire(run: () => Promise<void>): void {
  void run().catch(() => {
    // No-op: a device without haptics support must never raise here.
  });
}

/** Beat 1 — an entry resolved (shimmer → value): a soft, light tap. */
export function entryResolvedHaptic(): void {
  fire(() => Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light));
}

/** Beat 2 — a correction saved: a success notification. */
export function correctionSavedHaptic(): void {
  fire(() =>
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success),
  );
}

/** Beat 3 — the day's calorie target reached: a success notification. */
export function targetReachedHaptic(): void {
  fire(() =>
    Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success),
  );
}
