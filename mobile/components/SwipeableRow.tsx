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
} from "react-native";

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
 * Standard iOS swipe-left-to-delete for a Today timeline row (FTY-322).
 *
 * Left-swiping the row slides it aside to reveal a single destructive **Delete**
 * button; tapping it deletes (the swipe reveal is the confirmation, per native
 * convention — no extra confirm alert). Built on React Native core
 * `Animated` + `PanResponder` (the app ships no `react-native-gesture-handler`),
 * so it adds **no dependency**. The gesture only claims the responder on a clear
 * horizontal drag (`|dx| > |dy|`), so a plain tap still falls through to the
 * child row's own press handler (tap-to-correct / Retry stay intact) and the
 * enclosing vertical `ScrollView` keeps its drags.
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
      // The handlers below read `offset.current` and drive `translateX`, but only
      // at gesture (event) time — never during render — so the mutable ref is the
      // correct store and there is no stale-closure risk (same rationale the
      // Skeleton shimmer ref documents). The rule can't see the deferral.
      // eslint-disable-next-line react-hooks/refs
      PanResponder.create({
        // Never claim on a plain touch-down — taps pass through to the child row.
        onStartShouldSetPanResponder: () => false,
        onMoveShouldSetPanResponder: (_evt, gesture) =>
          Math.abs(gesture.dx) > HORIZONTAL_ACTIVATION &&
          Math.abs(gesture.dx) > Math.abs(gesture.dy),
        onPanResponderMove: (_evt, gesture) => {
          const next = offset.current + gesture.dx;
          // Clamp: reveal at most the action width on the left, never overshoot right.
          const clamped = Math.max(-DELETE_ACTION_WIDTH, Math.min(0, next));
          translateX.setValue(clamped);
        },
        onPanResponderRelease: (_evt, gesture) => {
          const next = offset.current + gesture.dx;
          settle(next <= -OPEN_THRESHOLD ? -DELETE_ACTION_WIDTH : 0);
        },
        onPanResponderTerminate: () => {
          settle(offset.current <= -OPEN_THRESHOLD ? -DELETE_ACTION_WIDTH : 0);
        },
      }),
    [settle, translateX],
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
