import { useRouter } from 'expo-router';

import { TodayScreen } from '@/components/TodayScreen';

/**
 * Today tab — the status-first home screen.
 * Wires the existing TodayScreen into the Today tab; passes the profile
 * navigation callback so the TodayScreen's header can route to profile/settings.
 */
export default function TodayTab() {
  const router = useRouter();
  return <TodayScreen onPressProfile={() => router.push('/profile')} />;
}
