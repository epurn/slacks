import { useMemo, useRef, useState, type ReactNode } from "react";
import {
  AccessibilityInfo,
  Animated,
  PanResponder,
  Pressable,
  StyleSheet,
  Text,
  View,
  type AccessibilityActionEvent,
  type PanResponderCallbacks,
  type PanResponderGestureState,
} from "react-native";

import {
  useSwipeScrollLock,
  type SetScrollLocked,
} from "@/components/today/swipeScrollLock";
import { useTheme, spacing, typeScale } from "@/theme";
import { defaultSpring, useReduceMotion } from "@/theme/motion";

/**
 * The accessibility props a {@link SwipeableRow} hands its child row so the
 * Delete action is reachable by VoiceOver on the row's own accessible element —
 * the swipe gesture is a pointer affordance only, so the equivalent action must
 * live on the focused control, not on the (non-accessible) gesture wrapper. The
 * child spreads these onto its interactive element (see `ItemTimelineRow` /
 * `EntryRow`).
 */
export interface SwipeDeleteAccessibilityProps {
  readonly accessibilityActions: readonly { name: string; label: string }[];
  readonly onAccessibilityAction: (event: AccessibilityActionEvent) => void;
}

/** Width of the revealed destructive action; comfortably past the 44pt min. */
const DELETE_ACTION_WIDTH = 88;
/** Swipe past this fraction of the action width to latch it open on release. */
const OPEN_THRESHOLD = DELETE_ACTION_WIDTH * 0.5;
/** Ignore sub-pixel jitter; only claim the gesture past a clear horizontal drag. */
const HORIZONTAL_ACTIVATION = 8;

/**
 * Whether a move should be claimed as the row's horizontal swipe rather than
 * left to the enclosing vertical scroll (FTY-417). The drag must clear the
 * activation slop *and* be horizontally dominant (`|dx| > |dy|`): a horizontal
 * drag claims the responder and opens the reveal; a vertical drag falls through
 * so the timeline keeps scrolling. Pure so the arbitration is unit-testable with
 * synthetic gesture states, exactly as FTY-322/417's row tests drive it.
 */
export function shouldClaimHorizontalSwipe(dx: number, dy: number): boolean {
  return Math.abs(dx) > HORIZONTAL_ACTIVATION && Math.abs(dx) > Math.abs(dy);
}

/** The mutable pieces {@link buildSwipeResponderConfig} drives at gesture time. */
interface SwipeResponderDeps {
  /** Resting offset the current drag is measured from (0 closed, negative open). */
  readonly offset: { current: number };
  /** Drives the row translate during the drag. */
  readonly translateX: Animated.Value;
  /** Latches the row to a rest position (open/closed) with the release spring. */
  readonly settle: (toValue: number) => void;
  /** Lock/unlock the enclosing scroll for the duration of an active swipe. */
  readonly setScrollLocked: SetScrollLocked | null;
}

/**
 * The `PanResponder` config for the swipe-to-delete row, extracted as a pure
 * factory so the gesture *arbitration* — the crux of FTY-417 — is unit-testable
 * without simulating native touch history.
 *
 * Three things make the horizontal swipe win cleanly over the vertical scroll:
 *
 *  - **Direction-gated claim.** `onMoveShouldSetPanResponder` only claims on a
 *    clear horizontal drag (see {@link shouldClaimHorizontalSwipe}), so a plain
 *    tap falls through to the child row's press handler and a vertical drag falls
 *    through to the scroll.
 *  - **No voluntary yield.** `onPanResponderTerminationRequest` returns `false`:
 *    once this row owns the gesture the enclosing `ScrollView` cannot request it
 *    back, so `onPanResponderTerminate` no longer fires mid-swipe and the reveal
 *    stops snapping shut (the "3-4 tries" bug). `onShouldBlockNativeResponder`
 *    returns `true` so the Android native scroll responder is blocked too.
 *  - **Scroll yields on grant.** On grant the row locks the enclosing scroll and
 *    on release/terminate it unlocks — belt-and-braces so the scroll container
 *    never reclaims the pan for the duration of an active horizontal swipe.
 *
 * The revealed state stays latched open after release (offset holds the open
 * rest position) until the user taps Delete, taps away, or swipes it closed — it
 * is never auto-snapped shut on an ambiguous release.
 */
export function buildSwipeResponderConfig({
  offset,
  translateX,
  settle,
  setScrollLocked,
}: SwipeResponderDeps): PanResponderCallbacks {
  return {
    // Never claim on a plain touch-down — taps pass through to the child row.
    onStartShouldSetPanResponder: () => false,
    onMoveShouldSetPanResponder: (_evt, gesture: PanResponderGestureState) =>
      shouldClaimHorizontalSwipe(gesture.dx, gesture.dy),
    onPanResponderGrant: () => {
      // Horizontal intent is now clear and this row owns the gesture: stop the
      // enclosing timeline scroll so it cannot reclaim the pan and snap the
      // half-open reveal shut mid-swipe (FTY-417).
      setScrollLocked?.(true);
    },
    onPanResponderMove: (_evt, gesture: PanResponderGestureState) => {
      const next = offset.current + gesture.dx;
      // Clamp: reveal at most the action width on the left, never overshoot right.
      const clamped = Math.max(-DELETE_ACTION_WIDTH, Math.min(0, next));
      translateX.setValue(clamped);
    },
    // Refuse to hand the gesture back to the scroll container once claimed — this
    // is what stops the reveal from being canceled by a scroll reclaim (FTY-417).
    onPanResponderTerminationRequest: () => false,
    // Android: the JS pan is authoritative, so block the native scroll responder.
    onShouldBlockNativeResponder: () => true,
    onPanResponderRelease: (_evt, gesture: PanResponderGestureState) => {
      setScrollLocked?.(false);
      const next = offset.current + gesture.dx;
      // Latch to the nearer rest state and stay there — never auto-snap shut on
      // an ambiguous release once the reveal is past the open threshold.
      settle(next <= -OPEN_THRESHOLD ? -DELETE_ACTION_WIDTH : 0);
    },
    onPanResponderTerminate: () => {
      // Reached only on an OS-forced termination (e.g. an incoming-call banner),
      // since voluntary termination is refused above. Re-enable scroll and latch
      // to the nearest rest state from the last resting offset.
      setScrollLocked?.(false);
      settle(offset.current <= -OPEN_THRESHOLD ? -DELETE_ACTION_WIDTH : 0);
    },
  };
}

/**
 * Standard iOS swipe-left-to-delete for a Today timeline row (FTY-322).
 *
 * Left-swiping the row slides it aside to reveal a single destructive **Delete**
 * button; tapping it deletes (the swipe reveal is the confirmation, per native
 * convention — no extra confirm alert). Built on React Native core
 * `Animated` + `PanResponder` (the app ships no `react-native-gesture-handler`),
 * so it adds **no dependency**. The gesture only claims the responder on a clear
 * horizontal drag (`|dx| > |dy|`), so a plain tap still falls through to the
 * child row's own press handler (tap-to-correct / Retry stay intact) and a
 * vertical drag falls through to the enclosing timeline scroll.
 *
 * Once a horizontal swipe is claimed it wins *cleanly* over that scroll (FTY-417):
 * the responder refuses to yield the gesture back (`onPanResponderTerminationRequest`
 * → `false`) and the enclosing `ScrollView` is locked for the duration of the
 * swipe (via {@link useSwipeScrollLock}), so the reveal no longer snaps shut when
 * the scroll view reclaims the pan mid-drag. The revealed state latches open on
 * release until an explicit close. See {@link buildSwipeResponderConfig}.
 *
 * Motion stays calm: the release spring uses the restrained default, and under
 * Reduce Motion the row snaps without animating. The revealed button is ≥44pt
 * and, because the swipe is pointer-only, the same Delete is exposed to
 * assistive tech as a custom action on the row via {@link SwipeDeleteAccessibilityProps};
 * committing it announces the removal.
 */
export function SwipeableRow({
  onDelete,
  deleteAccessibilityLabel,
  deleteAnnouncement,
  testID,
  children,
}: {
  /** Commit the delete (optimistic removal is the caller's concern). */
  onDelete: () => void;
  /** VoiceOver label for the revealed button and the row's custom action target. */
  deleteAccessibilityLabel: string;
  /** Announced to assistive tech when the delete commits (calm confirmation). */
  deleteAnnouncement?: string;
  testID?: string;
  /** Render-prop: the child row spreads the passed a11y props onto its control. */
  children: (a11y: SwipeDeleteAccessibilityProps) => ReactNode;
}) {
  const { colors } = useTheme();
  const reduceMotion = useReduceMotion();
  // Lock the enclosing Today scroll while a horizontal swipe is active so it
  // cannot reclaim the pan and cancel the reveal (FTY-417). Null off-screen /
  // outside the Today ScrollView, where the row still works via the responder's
  // own no-yield termination setting.
  const setScrollLocked = useSwipeScrollLock();

  // Lazy state initializer so the Animated.Value is created exactly once and is
  // safe to read during render for the transform (matches CalorieHero /
  // FloatingSwitcher; avoids reading a ref's `current` in render).
  const [translateX] = useState(() => new Animated.Value(0));
  // The resting offset the current drag is measured from (0 closed, negative
  // open). A ref, not state: the pan responder reads/writes it synchronously in
  // the gesture handlers (event time, never render) and it must not trigger a
  // re-render mid-gesture.
  const offset = useRef(0);

  const settle = useMemo(() => {
    return (toValue: number) => {
      offset.current = toValue;
      if (reduceMotion) {
        translateX.setValue(toValue);
        return;
      }
      Animated.spring(translateX, {
        ...defaultSpring,
        toValue,
        useNativeDriver: false,
      }).start();
    };
  }, [reduceMotion, translateX]);

  const commitDelete = useMemo(() => {
    return () => {
      if (deleteAnnouncement) {
        AccessibilityInfo.announceForAccessibility(deleteAnnouncement);
      }
      onDelete();
    };
  }, [deleteAnnouncement, onDelete]);

  const panResponder = useMemo(
    () =>
      PanResponder.create(
        // The config's handlers read `offset.current` and drive `translateX`, but
        // only at gesture (event) time — never during render — so the mutable ref
        // is the correct store and there is no stale-closure risk (same rationale
        // the Skeleton shimmer ref documents). The rule can't see the deferral.
        // eslint-disable-next-line react-hooks/refs
        buildSwipeResponderConfig({ offset, translateX, settle, setScrollLocked }),
      ),
    [setScrollLocked, settle, translateX],
  );

  const a11y: SwipeDeleteAccessibilityProps = useMemo(
    () => ({
      accessibilityActions: [{ name: "delete", label: "Delete" }],
      onAccessibilityAction: (event: AccessibilityActionEvent) => {
        if (event.nativeEvent.actionName === "delete") {
          commitDelete();
        }
      },
    }),
    [commitDelete],
  );

  return (
    <View testID={testID} style={styles.container}>
      {/* The destructive action sits behind the row and is revealed on swipe. */}
      <View style={styles.actionLayer} pointerEvents="box-none">
        <Pressable
          testID="swipe-delete-action"
          onPress={commitDelete}
          style={[styles.deleteButton, { backgroundColor: colors.coral }]}
          accessibilityRole="button"
          accessibilityLabel={deleteAccessibilityLabel}
        >
          <Text style={styles.deleteLabel}>Delete</Text>
        </Pressable>
      </View>

      {/* The row content. Its opaque background hides the action when closed so
          the red never bleeds through a transparent row. */}
      <Animated.View
        style={[
          styles.content,
          { backgroundColor: colors.surfaceRaised, transform: [{ translateX }] },
        ]}
        {...panResponder.panHandlers}
      >
        {children(a11y)}
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    position: "relative",
    overflow: "hidden",
  },
  actionLayer: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: "flex-end",
    justifyContent: "center",
  },
  deleteButton: {
    height: "100%",
    width: DELETE_ACTION_WIDTH,
    minHeight: 44,
    alignItems: "center",
    justifyContent: "center",
    paddingHorizontal: spacing.sm,
  },
  deleteLabel: {
    color: "#FFFFFF",
    fontSize: typeScale.subhead,
    fontWeight: "600",
  },
  content: {
    width: "100%",
  },
});
