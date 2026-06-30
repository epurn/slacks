import { useRouter } from "expo-router";

import { TrendsScreen } from "@/components/TrendsScreen";
import { expoNotificationsAdapter, fileCadenceStore } from "@/state/cadenceAdapter";

/**
 * Trends tab — rebuilt for FTY-101.
 *
 * Wires TrendsScreen with the concrete cadence store (expo-file-system) and
 * notification adapter (expo-notifications). Past-day drilldown navigates to
 * /day?date=YYYY-MM-DD.
 */
export default function TrendsTab() {
  const router = useRouter();
  return (
    <TrendsScreen
      store={fileCadenceStore}
      notifications={expoNotificationsAdapter}
      onDayPress={(date) =>
        router.push({ pathname: "/day", params: { date } })
      }
      onPressProfile={() => router.push('/profile')}
    />
  );
}
