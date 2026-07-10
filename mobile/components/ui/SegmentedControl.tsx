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
 *
 * The one theming input we do drive is `appearance` (FTY-343): the native
 * `UISegmentedControl` otherwise paints for the *device* scheme, so when the app
 * renders dark on a light device (or via the `ColorSchemeOverride` seam) the
 * control shows in light appearance against the dark `colors.surface` and the
 * unselected label loses contrast (fails WCAG AA). Feeding the resolved
 * `useTheme()` scheme into the library's own `appearance` prop keeps it the
 * adaptive platform control while making it track the app's theme, not the OS's.
 */

import RNSegmentedControl from '@react-native-segmented-control/segmented-control';
import type { StyleProp, ViewStyle } from 'react-native';
import { StyleSheet, Text, View } from 'react-native';

import { useTheme } from '@/theme';
import { typeScale } from '@/theme/typography';

export interface SegmentedControlOption<T extends string> {
  value: T;
  label: string;
  /**
   * Optional descriptive copy for this option (FTY-222). The platform
   * `UISegmentedControl` exposes no per-segment accessibility-label hook — each
   * segment's title *is* its label and the library forwards no override — so a
   * description can't ride along the segment itself. Instead the wrapper renders
   * the *selected* option's description as a visible caption below the control,
   * updating as the selection changes. That surfaces the copy to every user
   * (previously it reached only VoiceOver via a bespoke per-radio group) and,
   * being ordinary on-screen text, it stays reachable by VoiceOver — no
   * information regression. Purely additive: options without the field render no
   * caption, exactly as before.
   */
  description?: string;
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
  const { colors, scheme } = useTheme();

  const selectedIndex = Math.max(
    0,
    options.findIndex((o) => o.value === selected),
  );
  const caption = options[selectedIndex]?.description;

  return (
    // The caller `style` sizes the outer layout box (row `flex`, width caps),
    // not the native control. The wrapper is a column with the default
    // `alignItems: 'stretch'`, so the control below fills the caller-sized
    // width; the caption stays anchored beneath it inside the same box. Applying
    // a caller's `flex`/width to the inner control instead would collapse the
    // no-flex wrapper to zero width (FTY-271).
    <View style={style}>
      <RNSegmentedControl
        testID={testID}
        accessibilityLabel={accessibilityLabel}
        // Render in the app's resolved theme, not the raw device scheme, so an
        // app-dark / device-light mismatch no longer paints a light control on
        // the dark surface and greys out the unselected label (FTY-343).
        appearance={scheme}
        values={options.map((o) => o.label)}
        selectedIndex={selectedIndex}
        onChange={(event) => {
          const index = event.nativeEvent.selectedSegmentIndex;
          const option = options[index];
          if (option) {
            onSelect(option.value);
          }
        }}
        style={styles.control}
      />
      {caption != null && caption !== '' && (
        <Text
          testID={testID ? `${testID}-caption` : undefined}
          accessibilityLiveRegion="polite"
          style={[styles.caption, { color: colors.textMuted }]}
        >
          {caption}
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  // Keep the native pill's look but guarantee the app-wide ≥44pt target.
  control: {
    minHeight: 44,
  },
  caption: {
    fontSize: typeScale.footnote,
    marginTop: 8,
    textAlign: 'center',
  },
});
