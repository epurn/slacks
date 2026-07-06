import { Pressable, StyleSheet, Text, type StyleProp, type ViewStyle } from 'react-native';
import { useTheme, radius, spacing, typeScale } from '@/theme';

/**
 * Shared tappable-chip primitive (FTY-193).
 *
 * Consolidates the app's one-off chip styles (radius, padding, `controlBackground`
 * fill, text token) into a single definition. The visible pill stays compact
 * (`minHeight` well under 44) so a dense chip strip never balloons, while
 * `CHIP_HIT_SLOP` pads the *tappable* area out to the WCAG 2.5.5 44pt minimum —
 * `minHeight` + `hitSlop.top` + `hitSlop.bottom` always sums to exactly 44.
 */
export const CHIP_HIT_SLOP = { top: 8, bottom: 8 } as const;

interface ChipProps {
  /** Visible chip text. Used as the accessibility label unless one is given. */
  label: string;
  onPress: () => void;
  /** Overrides the default (`label`) accessibility label. */
  accessibilityLabel?: string;
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
  testID?: string;
}

export function Chip({
  label,
  onPress,
  accessibilityLabel,
  disabled = false,
  style,
  testID,
}: ChipProps) {
  const { colors } = useTheme();

  return (
    <Pressable
      testID={testID}
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? label}
      accessibilityState={{ disabled }}
      disabled={disabled}
      hitSlop={CHIP_HIT_SLOP}
      onPress={onPress}
      style={[styles.chip, { backgroundColor: colors.controlBackground }, style]}
    >
      <Text style={[styles.label, { color: colors.text }]} numberOfLines={1}>
        {label}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  chip: {
    minHeight: 28,
    minWidth: 44,
    paddingVertical: spacing.xs,
    paddingHorizontal: spacing.md,
    borderRadius: radius.full,
    justifyContent: 'center',
    alignItems: 'center',
  },
  label: {
    fontSize: typeScale.detail,
    fontWeight: '500',
  },
});
