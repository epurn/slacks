import { type TextProps } from 'react-native';
import { type TypeScaleKey } from '@/theme';
import { DisplayText } from './DisplayText';

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
 * Wraps DisplayText with fontVariant: ['tabular-nums'] so that live-updating
 * numbers keep a constant width and never jitter. Swap DISPLAY_FONT_FAMILY in
 * theme/typography.ts when the licensed geometric grotesque is bundled.
 */
export function ThemedNumber({
  value,
  scale = 'heroDisplay',
  variant = 'text',
  bold = true,
  style,
  ...rest
}: ThemedNumberProps) {
  return (
    <DisplayText scale={scale} variant={variant} bold={bold} tabularNums style={style} {...rest}>
      {String(value)}
    </DisplayText>
  );
}
