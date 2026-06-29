/**
 * Onboarding route (`/onboarding`) — goal-led first-run flow (FTY-103).
 *
 * Thin wrapper: the testable screen lives in `OnboardingScreen`. The root
 * layout's auth gate routes a signed-in user with an incomplete profile or no
 * active goal here; a returning user with an existing goal + profile is routed
 * straight to Today.
 *
 * On completion: marks onboarding done in the session flag (preventing the
 * gate from re-routing before the async re-check completes) and navigates to
 * Today.
 */

import { useCallback } from 'react';
import { useRouter } from 'expo-router';

import { OnboardingScreen } from '@/components/OnboardingScreen';
import { markOnboardingComplete } from '@/state/onboardingComplete';
import { useSession } from '@/state/session';

export default function OnboardingRoute() {
  const session = useSession();
  const router = useRouter();

  const handleComplete = useCallback(() => {
    if (session?.userId) {
      markOnboardingComplete(session.userId);
    }
    router.replace('/');
  }, [session, router]);

  // `session` is always non-null here: the auth gate routes signed-out users
  // to sign-in before they reach this screen.
  return (
    <OnboardingScreen
      session={session}
      onComplete={handleComplete}
    />
  );
}
