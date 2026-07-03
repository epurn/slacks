import { BlurView } from 'expo-blur';
import { Tabs } from 'expo-router';
import { StyleSheet } from 'react-native';

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
 * button. The bar is backed by a real `expo-blur` `BlurView` at the system
 * `.ultraThin` material (FTY-185), so scrolled content dims/occludes beneath it
 * as it does under any native iOS tab bar rather than reading fully legible
 * through the labels. The material follows light/dark; the container stays
 * `position: 'absolute'` with a transparent background so the blur shows and the
 * content scrolls under it (screens reserve bottom inset for the last row).
 */
export default function TabLayout() {
  const { colors, isDark } = useTheme();

  return (
    <Tabs
      screenOptions={{
        headerShown: false,
        tabBarActiveTintColor: colors.tabActive,
        tabBarInactiveTintColor: colors.tabInactive,
        tabBarBackground: () => (
          <BlurView
            tint={
              isDark
                ? 'systemUltraThinMaterialDark'
                : 'systemUltraThinMaterialLight'
            }
            intensity={100}
            style={StyleSheet.absoluteFill}
          />
        ),
        tabBarStyle: {
          position: 'absolute',
          backgroundColor: 'transparent',
          borderTopColor: colors.separator,
          borderTopWidth: StyleSheet.hairlineWidth,
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
