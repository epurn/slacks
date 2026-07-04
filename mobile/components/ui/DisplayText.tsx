import { Text, type TextProps } from 'react-native';
import {
  useTheme,
  typeScale,
  type TypeScaleKey,
  DISPLAY_FONT_FAMILY,
  displayTracking,
} from '@/theme';

interface DisplayTextProps extends TextProps {
  /** Typography scale key; defaults to 'largeTitle'. */
  scale?: TypeScaleKey;
  /** Color variant; defaults to 'text'. */
  variant?: 'text' | 'textSecondary' | 'textMuted' | 'accent' | 'accentText' | 'coral';
  bold?: boolean;
  /** Tabular (fixed-width) figures — for live-updating numerals that must not jitter. */
  tabularNums?: boolean;
}

/**
 * The one place DISPLAY_FONT_FAMILY + display tracking are applied. Every
 * display-face surface (hero numerals, headers) renders through this — or
 * through ThemedNumber, which wraps it — so swapping DISPLAY_FONT_FAMILY to
 * the licensed geometric grotesque updates every display surface at once.
 */
export function DisplayText({
  scale = 'largeTitle',
  variant = 'text',
  bold = true,
  tabularNums = false,
  style,
  ...rest
}: DisplayTextProps) {
  const { colors } = useTheme();
  return (
    <Text
      style={[
        {
          fontFamily: DISPLAY_FONT_FAMILY,
          fontSize: typeScale[scale],
          fontWeight: bold ? '700' : '400',
          color: colors[variant],
          letterSpacing: displayTracking,
          ...(tabularNums ? { fontVariant: ['tabular-nums'] as const } : null),
        },
        style,
      ]}
      {...rest}
    />
  );
}
