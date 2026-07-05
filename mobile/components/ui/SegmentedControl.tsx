/**
 * Shared native segmented control (FTY-186).
 *
 * A thin, typed wrapper over the platform `UISegmentedControl`
 * (`@react-native-segmented-control/segmented-control`) — the standard iOS
 * segmented control, with the library's matching Android/web rendering. It
 * replaces the hand-rolled pill-segment groups the app used to ship (Settings
 * units/appearance/cadence/goal, Trends range), per the design philosophy's
 * *Native skeleton, bespoke soul* principle: use standard controls, never
 * restyle system chrome.
 *
 * The API mirrors a value/label option list so callers keep speaking in their
 * own domain enum — value in, selection out — while the native control owns
 * presentation, sizing (this fixes the two-line "Every 2 weeks" wrap), VoiceOver
 * semantics (each segment announced with its label + selected state), and
 * light/dark. No `tintColor`/font overrides: the point is to stop styling the
 * system control, so it stays the adaptive platform default.
 */

import RNSegmentedControl from '@react-native-segmented-control/segmented-control';
import type { StyleProp, ViewStyle } from 'react-native';
import { StyleSheet } from 'react-native';

export interface SegmentedControlOption<T extends string> {
  value: T;
  label: string;
  /**
   * Optional VoiceOver label for this segment, announced *instead of* the bare
   * visible label when navigating the control — e.g. a pace segment shown as
   * "Steady" that should announce "Steady: ~0.5% of bodyweight / week —
   * recommended" (FTY-222).
   *
   * The platform `UISegmentedControl` exposes no per-segment accessibility-label
   * hook (each segment's title *is* its label, and the library forwards no
   * override), so when any option carries this field the wrapper folds the full
   * set into the control's own `accessibilityLabel`. That keeps the descriptive
   * copy in the accessibility tree — no information is lost versus a hand-rolled
   * per-radio group — without restyling or forking the native control. Purely
   * additive: options without the field render and announce exactly as before.
   */
  accessibilityLabel?: string;
}

export function SegmentedControl<T extends string>({
  options,
  selected,
  onSelect,
  accessibilityLabel,
  testID,
  style,
}: {
  options: readonly SegmentedControlOption<T>[];
  selected: T;
  onSelect: (value: T) => void;
  accessibilityLabel: string;
  testID?: string;
  style?: StyleProp<ViewStyle>;
}) {
  const selectedIndex = Math.max(
    0,
    options.findIndex((o) => o.value === selected),
  );

  // When any segment carries its own accessibility label, weave the full set
  // into the control label so VoiceOver still announces the descriptive copy
  // the native control can't attach per-segment. No per-segment labels → the
  // control label is unchanged (FTY-186 call sites keep their exact label).
  const hasPerSegmentLabels = options.some((o) => o.accessibilityLabel);
  const composedAccessibilityLabel = hasPerSegmentLabels
    ? `${accessibilityLabel}. ${options
        .map((o) => o.accessibilityLabel ?? o.label)
        .join('. ')}`
    : accessibilityLabel;

  return (
    <RNSegmentedControl
      testID={testID}
      accessibilityLabel={composedAccessibilityLabel}
      values={options.map((o) => o.label)}
      selectedIndex={selectedIndex}
      onChange={(event) => {
        const index = event.nativeEvent.selectedSegmentIndex;
        const option = options[index];
        if (option) {
          onSelect(option.value);
        }
      }}
      style={[styles.control, style]}
    />
  );
}

const styles = StyleSheet.create({
  // Keep the native pill's look but guarantee the app-wide ≥44pt target.
  control: {
    minHeight: 44,
  },
});
