import { SymbolView } from 'expo-symbols';
import type { SFSymbol } from 'sf-symbols-typescript';
import type { ColorValue } from 'react-native';

export type AppIconName = SFSymbol;

interface AppIconProps {
  name: AppIconName;
  size?: number;
  color?: ColorValue;
  accessibilityLabel?: string;
}

/**
 * Single icon primitive for all app chrome — tab icons, header affordances,
 * and controls. Wraps expo-symbols SymbolView so every glyph comes from one
 * coherent SF-Symbol set, styled with design-system tokens (tintColor carries
 * the active/inactive or text color from the theme).
 */
export function AppIcon({ name, size = 22, color, accessibilityLabel }: AppIconProps) {
  return (
    <SymbolView
      name={name}
      size={size}
      tintColor={color}
      accessibilityLabel={accessibilityLabel}
      accessibilityRole="image"
    />
  );
}
