/**
 * NativeSheet — a controlled bottom sheet with genuine iOS detents.
 *
 * On iOS it wraps react-native-screens' declarative `ScreenStack` /
 * `ScreenStackItem` to present a real UIKit sheet: native detents (medium/large
 * or fit-to-content), the system grabber, swipe-to-dismiss, VoiceOver focus
 * management, and the content-dims-behind material — none of which a plain React
 * Native `Modal` can do (it fakes detents by switching a `maxHeight`).
 *
 * ## Why this mechanism (chosen for FTY-183)
 *
 * Expo SDK 57 (managed) ships `react-native-screens@4`, whose `ScreenStackItem`
 * exposes the UIKit sheet knobs directly (`sheetAllowedDetents`,
 * `sheetLargestUndimmedDetentIndex`, `sheetGrabberVisible`, `sheetCornerRadius`,
 * …). expo-router's own `formSheet` presentation is the same native machinery,
 * but it is *route*-based: a sheet route receives only serialisable params. Our
 * sheets (`CorrectionSheet`, `WeightLogSheet`) are controlled components that
 * hand their parent screen live callbacks (`onItemChange`, `onClarificationResolved`,
 * `onSaved`) and a full item object — data a route param cannot carry. So we
 * drive the same native primitive directly and keep the controlled component
 * API. No native module outside the managed SDK is added.
 *
 * Reduce Motion, the dimming material, and VoiceOver announcement all come from
 * the native presentation controller on iOS, so we do not reimplement them.
 *
 * ## Non-iOS fallback
 *
 * The UIKit detent controller is iOS-only. Off iOS (Android, and the Jest
 * android project / E2E emulator) we present the *same controlled content* in a
 * `Modal`-based bottom-anchored sheet: an explicit height derived from the
 * initial detent (so a `flex: 1` body fills it instead of collapsing), a
 * decorative grabber, tap-outside / back-button dismissal, and a Reduce-Motion
 * check that drops the slide animation. This is the presentation that shipped
 * before FTY-183 and that the Maestro clarify flow drives to completion, so the
 * end-to-end save/resolve paths stay reachable on the tested platform.
 *
 * The sheet mounts only while `visible`, presenting over the current screen; on
 * iOS the screen behind stays visible through any undimmed detent (see
 * `largestUndimmedDetentIndex`). A native swipe/tap-outside dismissal calls
 * `onClose`.
 */

import {
  useCallback,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import {
  AccessibilityInfo,
  Modal,
  Platform,
  Pressable,
  StyleSheet,
  useWindowDimensions,
  View,
  type NativeSyntheticEvent,
  type StyleProp,
  type ViewStyle,
} from "react-native";
import { ScreenStack, ScreenStackItem } from "react-native-screens";

/** Detent stops, either explicit height fractions or a compact fit-to-content sheet. */
export type SheetDetents = number[] | "fitToContents";

export interface NativeSheetProps {
  /** Present the sheet when true; unmounts (native dismiss) when false. */
  visible: boolean;
  /** Called on any dismissal — native swipe/tap-outside or the caller's own action. */
  onClose: () => void;
  /**
   * Detents the sheet may rest at. `[0.5, 1]` = medium → large; `"fitToContents"`
   * = a true small sheet sized to its content.
   */
  detents: SheetDetents;
  /**
   * Index into `detents` of the largest detent for which the screen behind is
   * *not* dimmed (so it stays visible, e.g. the timeline behind the correction
   * sheet at medium). `"none"` dims at every detent; `"last"` never dims.
   */
  largestUndimmedDetentIndex?: number | "none" | "last";
  /** Detent the sheet opens at (index into `detents`). Defaults to the smallest. */
  initialDetentIndex?: number;
  /** Show the native drag grabber at the top. */
  grabberVisible?: boolean;
  /** Corner radius for the sheet; falls back to the system default when unset. */
  cornerRadius?: number;
  /** The sheet surface colour. */
  backgroundColor: string;
  /** VoiceOver label announcing the sheet on present. */
  accessibilityLabel?: string;
  /** Extra style for the sheet content container. */
  contentStyle?: StyleProp<ViewStyle>;
  children: ReactNode;
}

const BASE_SCREEN_ID = "native-sheet-presenter";
const SHEET_SCREEN_ID = "native-sheet-content";

/** Corner radius used by the non-iOS fallback when the caller sets none. */
const FALLBACK_CORNER_RADIUS = 16;

/** Track the OS Reduce-Motion setting so the fallback sheet can drop its slide. */
function useReduceMotion(): boolean {
  const [reduceMotion, setReduceMotion] = useState(false);
  useEffect(() => {
    let mounted = true;
    void AccessibilityInfo.isReduceMotionEnabled().then((enabled) => {
      if (mounted) setReduceMotion(enabled);
    });
    const subscription = AccessibilityInfo.addEventListener(
      "reduceMotionChanged",
      setReduceMotion,
    );
    return () => {
      mounted = false;
      subscription.remove();
    };
  }, []);
  return reduceMotion;
}

export function NativeSheet({
  visible,
  onClose,
  detents,
  largestUndimmedDetentIndex = "none",
  initialDetentIndex = 0,
  grabberVisible = true,
  cornerRadius,
  backgroundColor,
  accessibilityLabel,
  contentStyle,
  children,
}: NativeSheetProps) {
  const handleDismissed = useCallback(
    (_e: NativeSyntheticEvent<{ dismissCount: number }>) => {
      onClose();
    },
    [onClose],
  );
  const { height: windowHeight } = useWindowDimensions();
  const reduceMotion = useReduceMotion();

  if (!visible) return null;

  // ── Non-iOS: Modal-based bottom sheet ──────────────────────────────────────
  // UIKit detents don't exist off iOS. Present the same controlled content in a
  // bottom-anchored Modal so it renders and stays reachable to assistive tech
  // and the E2E harness.
  if (Platform.OS !== "ios") {
    // A numeric detent maps to an explicit sheet height (fraction of the window)
    // so a `flex: 1` body fills it rather than collapsing to a zero-height strip;
    // `fitToContents` sizes to its content under a 90% ceiling.
    const sheetHeightStyle: ViewStyle =
      detents === "fitToContents"
        ? { maxHeight: "90%" }
        : {
            height: Math.round(
              windowHeight *
                (detents[initialDetentIndex] ??
                  detents[detents.length - 1] ??
                  1),
            ),
          };
    const corner = cornerRadius ?? FALLBACK_CORNER_RADIUS;

    return (
      <Modal
        visible
        transparent
        animationType={reduceMotion ? "none" : "slide"}
        presentationStyle="overFullScreen"
        onRequestClose={onClose}
        accessibilityViewIsModal
      >
        <View style={styles.fallbackOverlay}>
          {/* Backdrop — tapping outside the sheet dismisses it. */}
          <Pressable
            style={StyleSheet.absoluteFill}
            onPress={onClose}
            accessibilityLabel="Close sheet"
            accessibilityRole="button"
          />
          <View
            accessibilityViewIsModal
            accessibilityLabel={accessibilityLabel}
            style={[
              styles.fallbackSheet,
              {
                backgroundColor,
                borderTopLeftRadius: corner,
                borderTopRightRadius: corner,
              },
              sheetHeightStyle,
              contentStyle,
            ]}
          >
            {grabberVisible ? (
              <View
                style={styles.fallbackGrabberWrap}
                accessibilityElementsHidden
                importantForAccessibility="no-hide-descendants"
              >
                <View style={styles.fallbackGrabber} />
              </View>
            ) : null}
            {children}
          </View>
        </View>
      </Modal>
    );
  }

  // ── iOS: genuine UIKit detent sheet ────────────────────────────────────────
  return (
    // Full-window overlay; `box-none` so the transparent presenter never eats
    // touches meant for the screen behind an undimmed detent.
    <View style={StyleSheet.absoluteFill} pointerEvents="box-none">
      <ScreenStack style={styles.stack}>
        {/*
          Transparent presenter screen. A native sheet is presented *over* a
          screen; this one is see-through so the app behind (e.g. the Today
          timeline) shows through the sheet's undimmed detent.
        */}
        <ScreenStackItem
          screenId={BASE_SCREEN_ID}
          stackPresentation="push"
          headerConfig={{ hidden: true }}
          style={styles.transparent}
          contentStyle={styles.transparent}
        />
        <ScreenStackItem
          screenId={SHEET_SCREEN_ID}
          stackPresentation="formSheet"
          headerConfig={{ hidden: true }}
          sheetAllowedDetents={detents}
          sheetInitialDetentIndex={initialDetentIndex}
          sheetLargestUndimmedDetentIndex={largestUndimmedDetentIndex}
          sheetGrabberVisible={grabberVisible}
          sheetCornerRadius={cornerRadius}
          nativeBackButtonDismissalEnabled
          onDismissed={handleDismissed}
          accessibilityViewIsModal
          accessibilityLabel={accessibilityLabel}
          style={[styles.sheet, { backgroundColor }]}
          contentStyle={[styles.sheet, { backgroundColor }, contentStyle]}
        >
          {children}
        </ScreenStackItem>
      </ScreenStack>
    </View>
  );
}

const styles = StyleSheet.create({
  stack: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    backgroundColor: "transparent",
  },
  transparent: {
    backgroundColor: "transparent",
  },
  sheet: {
    flex: 1,
  },
  // ── Non-iOS fallback ──
  fallbackOverlay: {
    flex: 1,
    justifyContent: "flex-end",
    backgroundColor: "rgba(0,0,0,0.35)",
  },
  fallbackSheet: {
    overflow: "hidden",
  },
  fallbackGrabberWrap: {
    alignItems: "center",
    paddingTop: 8,
    paddingBottom: 4,
  },
  fallbackGrabber: {
    width: 36,
    height: 4,
    borderRadius: 999,
    backgroundColor: "rgba(128,128,128,0.4)",
  },
});
