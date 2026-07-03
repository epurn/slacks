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
 * the native stack navigator. `headerLargeTitle` gives the true iOS large title with
 * the standard frost-on-scroll collapse. The header is *opaque* (not transparent):
 * an opaque native-stack header lays the screen content below the bar on both iOS and
 * Android, and on iOS `contentInsetAdjustmentBehavior="automatic"` (set on the
 * SettingsScreen scroll view) drives the large-title inset so no row collides with the
 * status-bar clock. A transparent header would float over content and require a manual
 * offset that fights the dynamic large-title height, so we keep it opaque and match its
 * background to the grouped-list surface. The background/text colours come from the
 * app's *resolved* appearance rather than the raw system scheme, so a Light/Dark/System
 * override is honoured. The gear pushes this screen, so we hide the back chevron and
 * present a Done action (right) that dismisses back to where the gear was opened. The
 * Done label (and header tint) use `accentText`, the AA-safe amber, rather than the raw
 * decorative `accent`: as normal-size text the accent falls below the contrast bar on
 * the light surface, whereas `accentText` meets WCAG AA on both surfaces.
 */
export default function ProfileRoute() {
  const { setAppearance } = useAppearanceController();
  const { colors } = useTheme();
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
          headerStyle: { backgroundColor: colors.surface },
          headerLargeStyle: { backgroundColor: colors.surface },
          headerShadowVisible: false,
          headerLargeTitleShadowVisible: false,
          headerBackVisible: false,
          headerTintColor: colors.accentText,
          headerTitleStyle: { color: colors.text },
          headerLargeTitleStyle: { color: colors.text },
          headerRight: () => (
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Done"
              testID="profile-done"
              onPress={handleDone}
              hitSlop={{ top: 12, bottom: 12, left: 12, right: 12 }}
              style={styles.doneButton}
            >
              <Text style={[styles.doneLabel, { color: colors.accentText }]}>
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
