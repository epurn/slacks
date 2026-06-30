import { Pressable } from 'react-native';
import { Tabs, useRouter } from 'expo-router';

import { AppIcon } from '@/components/ui';
import { useTheme } from '@/theme';

/** Gear icon button rendered in each tab's navigation header. */
function GearButton() {
  const router = useRouter();
  const { colors } = useTheme();
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Open profile"
      accessibilityHint="Opens profile and settings"
      onPress={() => router.push('/profile')}
      style={{ marginRight: 16, minWidth: 44, minHeight: 44, alignItems: 'center', justifyContent: 'center' }}
    >
      <AppIcon name="gear" size={22} color={colors.text} />
    </Pressable>
  );
}

/**
 * Two-tab shell: Today · Trends.
 *
 * Logging is consolidated onto Today (FTY-147) — Today is the single logging
 * surface and the dashboard — so the Log tab is gone and the core loop has no
 * extra navigation hop.
 *
 * Standard native tab bar — two equal SF-Symbol-style tabs, no raised center
 * button, semi-transparent background that approximates the system ultraThin
 * material (requires expo-blur BlurView for the true UIBlurEffect; using the
 * native translucent tab bar background for now — TODO when expo-blur is added).
 *
 * A gear icon in every tab's header routes to the profile/settings screen.
 */
export default function TabLayout() {
  const { colors, isDark } = useTheme();

  const tabBarBg = isDark
    ? 'rgba(28,28,30,0.92)'
    : 'rgba(242,242,247,0.92)';

  return (
    <Tabs
      screenOptions={{
        headerShown: true,
        headerStyle: { backgroundColor: colors.surface },
        headerTintColor: colors.text,
        headerShadowVisible: false,
        headerRight: () => <GearButton />,
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
          // TodayScreen draws its own large "Today" title, refresh, and gear
          // (it predates the tab shell and owns its chrome + tests). Suppress
          // the native header here so the user doesn't see a duplicate "Today"
          // title and a second gear button. The placeholder tabs keep the
          // native header (and its gear), so the gear stays reachable on every
          // tab.
          headerShown: false,
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
