import { Tabs } from 'expo-router';

import { AppIcon } from '@/components/ui';
import { useTheme } from '@/theme';

/**
 * Two-tab shell: Today · Trends.
 *
 * Logging is consolidated onto Today (FTY-147) — Today is the single logging
 * surface and the dashboard — so the Log tab is gone and the core loop has no
 * extra navigation hop.
 *
 * Native header is suppressed globally (`headerShown: false`). Each screen
 * owns its chrome through the shared `ScreenHeader` component (FTY-151) —
 * one consistent large title + right-actions slot per screen, so there is no
 * duplicate title and no per-screen top-inset inconsistency.
 *
 * Standard native tab bar — two equal SF-Symbol-style tabs, no raised center
 * button, semi-transparent background that approximates the system ultraThin
 * material (requires expo-blur BlurView for the true UIBlurEffect; using the
 * native translucent tab bar background for now — TODO when expo-blur is added).
 */
export default function TabLayout() {
  const { colors, isDark } = useTheme();

  const tabBarBg = isDark
    ? 'rgba(28,28,30,0.92)'
    : 'rgba(242,242,247,0.92)';

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.tabActive,
        tabBarInactiveTintColor: colors.tabInactive,
        tabBarStyle: {
          position: 'absolute',
          backgroundColor: tabBarBg,
          borderTopColor: colors.separator,
          borderTopWidth: 0.5,
        },
      }}
    >
      <Tabs.Screen
        name="index"
        options={{
          title: 'Today',
          tabBarAccessibilityLabel: 'Today tab',
          tabBarIcon: ({ color }) => (
            <AppIcon name="sun.max" size={22} color={color} />
          ),
        }}
      />
      <Tabs.Screen
        name="trends"
        options={{
          title: 'Trends',
          tabBarAccessibilityLabel: 'Trends tab',
          tabBarIcon: ({ color }) => (
            <AppIcon name="chart.line.uptrend.xyaxis" size={22} color={color} />
          ),
        }}
      />
    </Tabs>
  );
}
