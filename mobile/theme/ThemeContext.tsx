import {
  createContext,
  useContext,
  useMemo,
  type ReactNode,
} from 'react';
import { useColorScheme } from 'react-native';

import { lightPalette, darkPalette, type ColorPalette } from './colors';

export type ColorSchemeOverride = 'light' | 'dark' | 'system';

interface ThemeContextValue {
  readonly colors: ColorPalette;
  readonly isDark: boolean;
  /**
   * The active resolved scheme ('light' | 'dark').
   * Always a concrete value — never 'system'.
   */
  readonly scheme: 'light' | 'dark';
}

const ThemeContext = createContext<ThemeContextValue>({
  colors: lightPalette,
  isDark: false,
  scheme: 'light',
});

/**
 * Resolves the active theme palette from the system color scheme.
 * Accepts an optional explicit `override` for Light / Dark / System user
 * preference (the Settings UI is a separate story; only the seam is wired here).
 * Defaults to following the system.
 */
export function ThemeProvider({
  children,
  override = 'system',
}: {
  children?: ReactNode;
  override?: ColorSchemeOverride;
}) {
  const systemScheme = useColorScheme();

  const value = useMemo<ThemeContextValue>(() => {
    const resolved: 'light' | 'dark' =
      override === 'system'
        ? (systemScheme === 'dark' ? 'dark' : 'light')
        : override;
    return {
      colors: resolved === 'dark' ? darkPalette : lightPalette,
      isDark: resolved === 'dark',
      scheme: resolved,
    };
  }, [override, systemScheme]);

  return (
    <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>
  );
}

/**
 * Access the active theme palette and scheme inside any component.
 * Must be called within a ThemeProvider subtree.
 */
export function useTheme(): ThemeContextValue {
  return useContext(ThemeContext);
}
