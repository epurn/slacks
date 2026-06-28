import { Text, type TextProps } from 'react-native';
import {
  useTheme,
  typeScale,
  type TypeScaleKey,
  DISPLAY_FONT_FAMILY,
  displayTracking,
} from '@/theme';

interface ThemedNumberProps extends TextProps {
  /** The numeric value to display (string or number). */
  value: string | number;
  /** Typography scale; defaults to 'heroDisplay' for hero numerals. */
  scale?: TypeScaleKey;
  /** Color variant; defaults to 'text'. */
  variant?: 'text' | 'textSecondary' | 'accent' | 'accentText' | 'coral';
  bold?: boolean;
}

/**
 * Display-face number primitive with tabular figures.
 *
 * Uses the DISPLAY_FONT_FAMILY token (currently the system font) with
 * fontVariant: ['tabular-nums'] so that live-updating numbers keep a constant
 * width and never jitter. Swap DISPLAY_FONT_FAMILY in theme/typography.ts when
 * the licensed geometric grotesque is bundled.
 */
export function ThemedNumber({
  value,
  scale = 'heroDisplay',
  variant = 'text',
  bold = true,
  style,
  ...rest
}: ThemedNumberProps) {
  const { colors } = useTheme();
  return (
    <Text
      style={[
        {
          fontFamily: DISPLAY_FONT_FAMILY,
          fontSize: typeScale[scale],
          fontWeight: bold ? '700' : '400',
          color: colors[variant],
          fontVariant: ['tabular-nums'],
          letterSpacing: displayTracking,
        },
        style,
      ]}
      {...rest}
    >
      {String(value)}
    </Text>
  );
}
