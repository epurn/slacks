import { Pressable, Text, type PressableProps, type StyleProp, type ViewStyle } from 'react-native';
import { useTheme, radius, typeScale } from '@/theme';

type ButtonVariant = 'primary' | 'secondary';

interface ButtonProps extends Omit<PressableProps, 'style'> {
  label: string;
  variant?: ButtonVariant;
  /** When true, the button shows a disabled state and is not interactive. */
  disabled?: boolean;
  style?: StyleProp<ViewStyle>;
}

/**
 * Themed Button primitive.
 *
 * Primary: amber accent background with high-contrast dark ink
 * (`accentForeground`) — readable in both light and dark (a near-white label
 * on the light dark-mode amber would fail WCAG contrast).
 * Secondary: muted control background with primary text.
 *
 * Minimum touch target is 44×44pt (WCAG success criterion 2.5.5).
 */
export function Button({
  label,
  variant = 'primary',
  disabled = false,
  style,
  ...rest
}: ButtonProps) {
  const { colors } = useTheme();

  const isPrimary = variant === 'primary';
  const bg = isPrimary ? colors.accent : colors.controlBackground;
  const textColor = isPrimary ? colors.accentForeground : colors.textSecondary;
  const opacity = disabled ? 0.45 : 1;

  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={label}
      accessibilityState={{ disabled }}
      disabled={disabled}
      style={[
        {
          minHeight: 44,
          minWidth: 44,
          paddingVertical: 12,
          paddingHorizontal: 20,
          borderRadius: radius.md,
          backgroundColor: bg,
          alignItems: 'center',
          justifyContent: 'center',
          opacity,
        },
        style,
      ]}
      {...rest}
    >
      <Text
        style={{
          fontSize: typeScale.callout,
          fontWeight: '600',
          color: textColor,
        }}
      >
        {label}
      </Text>
    </Pressable>
  );
}
