import { useEffect } from 'react';
import {
  Stack,
  useRootNavigationState,
  useRouter,
  useSegments,
} from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AppearanceProvider } from '@/state/appearance';
import {
  ConnectionProvider,
  shouldRedirectToConnect,
  useConnection,
} from '@/state/connection';
import { SessionProvider } from '@/state/session';
import { useTheme } from '@/theme';

/** StatusBar style driven by the active theme. */
function ThemedStatusBar() {
  const { isDark } = useTheme();
  return <StatusBar style={isDark ? 'light' : 'dark'} />;
}

/**
 * First-run routing gate (FTY-107). Once the persisted connection is hydrated, a
 * launch with no connected server is sent to the connect screen — the
 * self-host-first first step. It never forces a connected user off the connect
 * screen, so the "change server" affordance can route back to it intentionally.
 * FTY-091 layers the sign-in/auth states on top of this connection gate.
 */
function ConnectionGate() {
  const { status, connection } = useConnection();
  const segments = useSegments();
  const router = useRouter();
  const navState = useRootNavigationState();

  useEffect(() => {
    // Wait until the root navigator is mounted before navigating.
    if (!navState?.key) return;
    const atConnectScreen = segments[0] === 'connect';
    if (shouldRedirectToConnect(status, connection, atConnectScreen)) {
      router.replace('/connect');
    }
  }, [navState?.key, status, connection, segments, router]);

  return null;
}

/**
 * Root layout. Provides the design-system theme, the connected-server state, and
 * the authenticated-session context to every screen. The Stack hosts the tab
 * group plus the modal/standalone screens (connect, profile, weight). StatusBar
 * style is resolved from the active theme. `ConnectionProvider` hydrates the
 * persisted server connection on launch (and mirrors it into the synchronous
 * `resolveApiBaseUrl()` accessor); `SessionProvider` hydrates the persisted
 * session; `AppearanceProvider` hydrates the Light / Dark / System preference.
 */
export default function RootLayout() {
  return (
    <AppearanceProvider>
      <ConnectionProvider>
        <SessionProvider>
          <SafeAreaProvider>
            <ThemedStatusBar />
            <ConnectionGate />
            <Stack screenOptions={{ headerShown: false }} />
          </SafeAreaProvider>
        </SessionProvider>
      </ConnectionProvider>
    </AppearanceProvider>
  );
}
