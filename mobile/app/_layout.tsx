import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { ThemeProvider, useTheme } from '@/theme';

/** StatusBar style driven by the active theme. */
function ThemedStatusBar() {
  const { isDark } = useTheme();
  return <StatusBar style={isDark ? 'light' : 'dark'} />;
}

/**
 * Root layout. Provides the design-system theme context to every screen.
 * The Stack hosts the tab group plus the modal screens (profile, weight).
 * StatusBar style is resolved from the active theme rather than hardcoded.
 */
export default function RootLayout() {
  return (
    <ThemeProvider>
      <SafeAreaProvider>
        <ThemedStatusBar />
        <Stack screenOptions={{ headerShown: false }} />
      </SafeAreaProvider>
    </ThemeProvider>
  );
}
