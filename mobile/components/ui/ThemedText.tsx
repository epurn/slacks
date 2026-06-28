import { Text, type TextProps } from 'react-native';
import { useTheme, typeScale, type TypeScaleKey, BODY_FONT_FAMILY } from '@/theme';

interface ThemedTextProps extends TextProps {
  /** Typography scale key; defaults to 'body'. */
  scale?: TypeScaleKey;
  /** Color variant. Defaults to 'text' (primary). */
  variant?: 'text' | 'textSecondary' | 'textMuted' | 'accent' | 'accentText' | 'coral';
  bold?: boolean;
}

/**
 * Themed Text primitive. Reads color and size from the active theme.
 * Body text uses the system font (SF Pro) to honour Dynamic Type.
 * Pass `scale` for different size levels.
 */
export function ThemedText({
  scale = 'body',
  variant = 'text',
  bold = false,
  style,
  ...rest
}: ThemedTextProps) {
  const { colors } = useTheme();
  return (
    <Text
      style={[
        {
          fontFamily: BODY_FONT_FAMILY,
          fontSize: typeScale[scale],
          color: colors[variant],
          fontWeight: bold ? '700' : '400',
        },
        style,
      ]}
      {...rest}
    />
  );
}
