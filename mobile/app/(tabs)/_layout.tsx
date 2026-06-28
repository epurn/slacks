import { Pressable, Text } from 'react-native';
import { Tabs, useRouter } from 'expo-router';

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
      <Text style={{ fontSize: 22, color: colors.text }}>⚙</Text>
    </Pressable>
  );
}

/**
 * Three-tab shell: Today · Log · Trends.
 *
 * Standard native tab bar — three equal SF-Symbol-style tabs, no raised center
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
            <Text style={{ fontSize: 22, color }}>☀</Text>
          ),
        }}
      />
      <Tabs.Screen
        name="log"
        options={{
          title: 'Log',
          tabBarAccessibilityLabel: 'Log tab',
          tabBarIcon: ({ color }) => (
            <Text style={{ fontSize: 22, color }}>＋</Text>
          ),
        }}
      />
      <Tabs.Screen
        name="trends"
        options={{
          title: 'Trends',
          tabBarAccessibilityLabel: 'Trends tab',
          tabBarIcon: ({ color }) => (
            <Text style={{ fontSize: 22, color }}>📈</Text>
          ),
        }}
      />
    </Tabs>
  );
}
