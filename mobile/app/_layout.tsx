import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AppearanceProvider } from '@/state/appearance';
import { SessionProvider } from '@/state/session';
import { useTheme } from '@/theme';

/** StatusBar style driven by the active theme. */
function ThemedStatusBar() {
  const { isDark } = useTheme();
  return <StatusBar style={isDark ? 'light' : 'dark'} />;
}

/**
 * Root layout. Provides the design-system theme and the authenticated-session
 * context to every screen. The Stack hosts the tab group plus the modal screens
 * (profile, weight). StatusBar style is resolved from the active theme rather
 * than hardcoded. `SessionProvider` hydrates the persisted session on launch so
 * a signed-in user survives an app restart. `AppearanceProvider` hydrates the
 * persisted Light / Dark / System preference and drives the theme from it, so a
 * chosen appearance is live on selection and restored on the next launch.
 */
export default function RootLayout() {
  return (
    <AppearanceProvider>
      <SessionProvider>
        <SafeAreaProvider>
          <ThemedStatusBar />
          <Stack screenOptions={{ headerShown: false }} />
        </SafeAreaProvider>
      </SessionProvider>
    </AppearanceProvider>
  );
}
