import { useCallback } from "react";
import { Pressable, StyleSheet, Text } from "react-native";
import { Stack, useRouter } from "expo-router";

import { SettingsScreen } from "@/components/SettingsScreen";
import { useAppearanceController } from "@/state/appearance";
import { useTheme, typeScale } from "@/theme";

/**
 * The Profile / Settings route (`/profile`). Opens from the header gear.
 *
 * Chrome (FTY-182): a real native large-title header with a Done action, backed by
 * the native stack navigator. `headerLargeTitle` + `headerBlurEffect` give the true
 * iOS large title with the standard frost-on-scroll; `contentInsetAdjustmentBehavior`
 * on the SettingsScreen scroll view (set there) insets content below the bar so no
 * row collides with the status-bar clock. The blur/text variants are chosen from the
 * app's *resolved* appearance rather than the raw system scheme, so a Light/Dark/System
 * override is honoured. The gear pushes this screen, so we hide the back chevron and
 * present a Done action (right) that dismisses back to where the gear was opened.
 */
export default function ProfileRoute() {
  const { setAppearance } = useAppearanceController();
  const { colors, isDark } = useTheme();
  const router = useRouter();

  const handleDone = useCallback(() => {
    router.back();
  }, [router]);

  return (
    <>
      <Stack.Screen
        options={{
          headerShown: true,
          title: "Profile",
          headerLargeTitle: true,
          headerTransparent: true,
          headerBlurEffect: isDark
            ? "systemChromeMaterialDark"
            : "systemChromeMaterialLight",
          headerShadowVisible: false,
          headerLargeTitleShadowVisible: false,
          headerBackVisible: false,
          headerTintColor: colors.accent,
          headerTitleStyle: { color: colors.text },
          headerLargeTitleStyle: { color: colors.text },
          headerRight: () => (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Done"
              onPress={handleDone}
              hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
              style={styles.doneButton}
            >
              <Text style={[styles.doneLabel, { color: colors.accent }]}>
                Done
              </Text>
            </Pressable>
          ),
        }}
      />
      <SettingsScreen onAppearanceChange={setAppearance} />
    </>
  );
}

const styles = StyleSheet.create({
  doneButton: {
    minHeight: 44,
    minWidth: 44,
    alignItems: "flex-end",
    justifyContent: "center",
  },
  doneLabel: {
    fontSize: typeScale.body,
    fontWeight: "600",
  },
});
