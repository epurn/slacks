import { StyleSheet, Text, View } from "react-native";

import { useTheme, spacing, typeScale } from "@/theme";

/**
 * The Today sign-in gate. Until the mobile sign-in flow lands there is no
 * session on the device, so this renders a clear, calm "sign in" state that
 * mirrors the profile capture flow.
 */
export function SignInRequired({ insetTop }: { insetTop: number }) {
  const { colors } = useTheme();
  return (
    <View style={[styles.center, { paddingTop: insetTop, backgroundColor: colors.surface }]}>
      <Text style={[styles.centerTitle, { color: colors.text }]} accessibilityRole="header">
        Sign in to see your day
      </Text>
      <Text style={[styles.centerBody, { color: colors.textMuted }]}>
        Your log is stored privately against your account. Sign in to add and
        review today&apos;s food and exercise.
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  center: {
    flex: 1,
    paddingHorizontal: spacing.xl,
    alignItems: "center",
  },
  centerTitle: {
    fontSize: 24,
    fontWeight: "700",
    textAlign: "center",
  },
  centerBody: {
    fontSize: typeScale.subhead,
    textAlign: "center",
    marginTop: spacing.md,
  },
});
