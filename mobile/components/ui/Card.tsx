import { View, type ViewProps } from 'react-native';
import { useTheme, radius } from '@/theme';

interface CardProps extends ViewProps {
  /** When true, use the raised surface colour (default). When false, use primary surface. */
  raised?: boolean;
}

/**
 * Flat opaque card surface. Carries theme-aware background and rounded corners.
 * Per the design philosophy: timeline cards are flat and opaque — not glass.
 */
export function Card({ raised = true, style, ...rest }: CardProps) {
  const { colors } = useTheme();
  return (
    <View
      style={[
        {
          backgroundColor: raised ? colors.surfaceRaised : colors.surface,
          borderRadius: radius.lg,
          overflow: 'hidden',
        },
        style,
      ]}
      {...rest}
    />
  );
}
