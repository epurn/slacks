import { Fragment, useCallback, useEffect, useRef, useState } from 'react';
import {
  Stack,
  useRootNavigationState,
  useRouter,
  useSegments,
} from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { getProfile, ProfileApiError } from '@/api/profile';
import { getTarget, GoalsApiError } from '@/api/goals';
import { AppearanceProvider } from '@/state/appearance';
import {
  resolveAuthRedirect,
  resolveOnboardingStatus,
  type OnboardingProbe,
  type OnboardingStatus,
} from '@/state/authRouting';
import { ConnectionProvider, useConnection } from '@/state/connection';
import {
  clearOnboardingComplete,
  isOnboardingCompleteForUser,
} from '@/state/onboardingComplete';
import { isProfileComplete } from '@/state/onboarding';
import {
  GoalDirectionProvider,
  useGoalDirectionController,
} from '@/state/goalDirection';
import {
  SessionProvider,
  toApiSession,
  useSessionController,
} from '@/state/session';
import { useTheme } from '@/theme';
import {
  isE2EMode,
  setupE2EMode,
  e2eSessionStore,
  e2eConnectionStore,
} from '@/e2e/launchMode';
import {
  useVisualReviewRevision,
  VisualReviewSettleOverlay,
} from '@/e2e/visualReview';

// Install the E2E mock fetch and mark onboarding complete for the synthetic
// user before any provider mounts. In release builds __DEV__ is false so
// setupE2EMode() returns immediately — this branch is dead code that Metro
// eliminates. See mobile/e2e/launchMode.ts for the security properties.
if (isE2EMode()) {
  setupE2EMode();
}

/** StatusBar style driven by the active theme. */
function ThemedStatusBar() {
  const { isDark } = useTheme();
  return <StatusBar style={isDark ? 'light' : 'dark'} />;
}

/**
 * Signed-out + onboarding routing gate (FTY-091 + FTY-103). Once both the
 * connection (FTY-107) and the session (FTY-090) have hydrated, and once the
 * onboarding check has resolved, this routes from one place — no server →
 * connect; no session → sign-in; signed-in incomplete → onboarding; signed-in
 * complete → Today. The decision itself is the pure `resolveAuthRedirect`
 * (unit-tested without a navigator).
 *
 * Onboarding status is checked once per session (when the userId changes).
 * After the user completes onboarding in the current process, a module-level
 * flag (`isOnboardingCompleteForUser`) prevents the gate from re-routing
 * before the async API re-check can confirm the newly-written data.
 */
function AuthGate() {
  const { status: connectionStatus, connection } = useConnection();
  const { status: sessionStatus, session } = useSessionController();
  const { clearGoalDirection } = useGoalDirectionController();
  const segments = useSegments();
  const router = useRouter();
  const navState = useRootNavigationState();

  // Track which userId was last checked and what the result was. The derived
  // onboardingStatus below avoids synchronous setState in effects.
  const [checkedForUserId, setCheckedForUserId] = useState<string | null>(null);
  const [checkedResult, setCheckedResult] = useState<'complete' | 'incomplete'>('incomplete');
  const prevAtOnboardingRef = useRef(false);
  const atOnboarding = segments[0] === 'onboarding';

  // Derive onboarding status without synchronous setState in effects:
  // — no userId → 'checking' (gate will route to sign-in anyway)
  // — module-level completion flag set → 'complete' (immediate after wizard)
  // — userId not yet checked → 'checking' (holds the gate)
  // — otherwise use the last API result
  const currentUserId = session?.userId ?? null;
  const onboardingStatus: OnboardingStatus = (() => {
    if (!currentUserId) return 'checking';
    if (isOnboardingCompleteForUser(currentUserId)) return 'complete';
    if (checkedForUserId !== currentUserId) return 'checking';
    return checkedResult;
  })();

  const checkOnboarding = useCallback(
    async (userId: string) => {
      if (!session) return;
      const apiSession = toApiSession(session);

      // Probe each data source, distinguishing a definitive "not set up" (404,
      // or a profile that loads but is incomplete) from "couldn't tell" (a
      // transient network failure or 5xx). Only a definitive absence is a
      // signal to onboard; an unknown holds the gate (see resolveOnboardingStatus).
      const profileProbe: OnboardingProbe = await getProfile(apiSession)
        .then((profile): OnboardingProbe =>
          isProfileComplete(profile) ? 'present' : 'absent',
        )
        .catch((e: unknown): OnboardingProbe =>
          e instanceof ProfileApiError && e.status === 404 ? 'absent' : 'unknown',
        );
      const targetProbe: OnboardingProbe = await getTarget(apiSession)
        .then((): OnboardingProbe => 'present')
        .catch((e: unknown): OnboardingProbe =>
          e instanceof GoalsApiError && e.status === 404 ? 'absent' : 'unknown',
        );

      const status = resolveOnboardingStatus(profileProbe, targetProbe);
      if (status === 'complete' || status === 'incomplete') {
        setCheckedForUserId(userId);
        setCheckedResult(status);
      }
      // Otherwise 'undetermined' — leave the check unrecorded so the derived
      // status stays 'checking' (the gate holds, never routing into onboarding)
      // and a later state change can retry, rather than trapping the user this
      // session.
    },
    [session],
  );

  useEffect(() => {
    const userId = session?.userId ?? null;

    if (!userId) {
      // Signed out: clear the module-level flag and reset the segment ref.
      // No setState needed — onboardingStatus derives to 'checking' when userId is null.
      clearOnboardingComplete();
      // A different account may sign in next; never carry a stale goal
      // direction across accounts (state/goalDirection.tsx).
      clearGoalDirection();
      prevAtOnboardingRef.current = false;
      return;
    }

    // Module-level flag set by the wizard on completion — status derives as 'complete'.
    if (isOnboardingCompleteForUser(userId)) return;

    const justLeftOnboarding = prevAtOnboardingRef.current && !atOnboarding;
    prevAtOnboardingRef.current = atOnboarding;

    // Check when the userId hasn't been checked yet, OR when the user just
    // left the onboarding screen (post-completion confirmation).
    if (checkedForUserId !== userId || justLeftOnboarding) {
      void checkOnboarding(userId);
    }
  }, [session?.userId, atOnboarding, checkOnboarding, checkedForUserId, clearGoalDirection]);

  useEffect(() => {
    // Wait until the root navigator is mounted before navigating.
    if (!navState?.key) return;

    const target = resolveAuthRedirect({
      connectionStatus,
      connection,
      sessionStatus,
      session,
      onboardingStatus,
      atConnect: segments[0] === 'connect',
      atSignin: segments[0] === 'signin',
      atOnboarding,
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
    onboardingStatus,
    segments,
    atOnboarding,
    router,
  ]);

  return null;
}

/**
 * Root layout. Provides the design-system theme, the connected-server state, and
 * the authenticated-session context to every screen. The Stack hosts the tab
 * group plus the modal/standalone screens (connect, signin, onboarding,
 * profile). StatusBar style is resolved from the active theme. `ConnectionProvider`
 * hydrates the persisted server connection on launch; `SessionProvider` hydrates
 * the persisted session; `AppearanceProvider` hydrates the Light / Dark / System
 * preference; `GoalDirectionProvider` holds the session-scoped goal direction
 * (state/goalDirection.tsx) that Settings/Onboarding set and Trends reads.
 */
export default function RootLayout() {
  const e2e = isE2EMode();
  return (
    <AppearanceProvider>
      <ConnectionProvider store={e2e ? e2eConnectionStore : undefined}>
        <SessionProvider store={e2e ? e2eSessionStore : undefined}>
          <GoalDirectionProvider>
            <SafeAreaProvider>
              <ThemedStatusBar />
              <NavigatorHost />
            </SafeAreaProvider>
          </GoalDirectionProvider>
        </SessionProvider>
      </ConnectionProvider>
    </AppearanceProvider>
  );
}

/**
 * The auth gate + navigator, keyed on the visual-review revision (FTY-247).
 *
 * Activating a visual-review preset (E2E only) bumps the revision, remounting
 * this subtree so the target screen mounts fresh with the preset's seeded
 * fixtures in place instead of showing stale data from a screen mounted before
 * activation. The `VisualReviewDriver` then navigates to the preset's route and
 * the `VisualReviewSettleOverlay` exposes the screenshot marker once the screen
 * has settled. In release / normal use the revision is a constant `0`, so the
 * key never changes and this behaves exactly like a plain `<AuthGate/> +
 * <Stack/>`; the driver and overlay render nothing.
 */
function NavigatorHost() {
  const revision = useVisualReviewRevision();
  return (
    <Fragment key={revision}>
      <AuthGate />
      <Stack screenOptions={{ headerShown: false }} />
      {/* Rendered after the navigator so its settled marker sits on top of the
          screen (not occluded), where screenshot automation can find it. */}
      <VisualReviewSettleOverlay />
    </Fragment>
  );
}
