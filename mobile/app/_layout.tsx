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
import { resolveAuthRedirect } from '@/state/authRouting';
import { ConnectionProvider, useConnection } from '@/state/connection';
import { SessionProvider, useSessionController } from '@/state/session';
import { useTheme } from '@/theme';

/** StatusBar style driven by the active theme. */
function ThemedStatusBar() {
  const { isDark } = useTheme();
  return <StatusBar style={isDark ? 'light' : 'dark'} />;
}

/**
 * Signed-out routing gate (FTY-091, layered on FTY-107's connection seam). Once
 * both the connection (FTY-107) and the session (FTY-090) have hydrated, this
 * routes the three signed-out states from one place — no server → connect; no
 * session → sign-in; signed in but stranded on sign-in → Today — so there is no
 * reachable dead-end. A connected user is never forced off the connect screen,
 * so the "change server" affordance can open it intentionally. The decision
 * itself is the pure `resolveAuthRedirect` (unit-tested without a navigator).
 */
function AuthGate() {
  const { status: connectionStatus, connection } = useConnection();
  const { status: sessionStatus, session } = useSessionController();
  const segments = useSegments();
  const router = useRouter();
  const navState = useRootNavigationState();

  useEffect(() => {
    // Wait until the root navigator is mounted before navigating.
    if (!navState?.key) return;
    const target = resolveAuthRedirect({
      connectionStatus,
      connection,
      sessionStatus,
      session,
      atConnect: segments[0] === 'connect',
      atSignin: segments[0] === 'signin',
    });
    if (target !== null) {
      router.replace(target);
    }
  }, [
    navState?.key,
    connectionStatus,
    connection,
    sessionStatus,
    session,
    segments,
    router,
  ]);

  return null;
}

/**
 * Root layout. Provides the design-system theme, the connected-server state, and
 * the authenticated-session context to every screen. The Stack hosts the tab
 * group plus the modal/standalone screens (connect, signin, profile, weight).
 * StatusBar
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
            <AuthGate />
            <Stack screenOptions={{ headerShown: false }} />
          </SafeAreaProvider>
        </SessionProvider>
      </ConnectionProvider>
    </AppearanceProvider>
  );
}
