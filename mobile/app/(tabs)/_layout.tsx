import { Tabs } from 'expo-router';

import { FloatingSwitcher, type FloatingSwitcherSegment } from '@/components/ui';

/**
 * Two-destination shell: Today · Trends.
 *
 * Logging is consolidated onto Today (FTY-147) — Today is the single logging
 * surface and the dashboard — so there is no Log destination and the core loop
 * has no extra navigation hop.
 *
 * Native header is suppressed globally (`headerShown: false`). Each screen owns
 * its chrome through the shared `ScreenHeader` component (FTY-151).
 *
 * The old full-width bottom tab bar is gone (FTY-242). Navigation now lives in a
 * bottom-left **floating glass switcher** — a compact segmented pill inspired by
 * the iOS 26 Photos chrome — rendered through the navigator's `tabBar` slot so
 * the Expo Router routes, navigation state, and deep links stay exactly as they
 * were while the screen presents full-screen behind the pill. Because the
 * switcher anchors with `position: absolute`, it reserves no layout height in the
 * tab-bar slot: the scene fills the screen and the pill floats over it. Screens
 * reserve their own bottom clearance via `floatingSwitcherClearance`.
 */

const SEGMENTS: readonly FloatingSwitcherSegment[] = [
  { key: 'index', label: 'Today', icon: 'sun.max' },
  { key: 'trends', label: 'Trends', icon: 'chart.line.uptrend.xyaxis' },
];

export default function TabLayout() {
  return (
    <Tabs
      screenOptions={{ headerShown: false }}
      tabBar={({ state, navigation }) => {
        const activeKey = state.routes[state.index]?.name ?? 'index';
        return (
          <FloatingSwitcher
            segments={SEGMENTS}
            activeKey={activeKey}
            onSelect={(key) => {
              const route = state.routes.find((r) => r.name === key);
              if (!route) return;
              const isFocused = key === activeKey;
              const event = navigation.emit({
                type: 'tabPress',
                target: route.key,
                canPreventDefault: true,
              });
              if (!isFocused && !event.defaultPrevented) {
                navigation.navigate(route.name);
              }
            }}
          />
        );
      }}
    >
      <Tabs.Screen name="index" options={{ title: 'Today' }} />
      <Tabs.Screen name="trends" options={{ title: 'Trends' }} />
    </Tabs>
  );
}
