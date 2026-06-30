import { StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { useTheme, spacing, typeScale } from "@/theme";

interface ScreenHeaderProps {
  title: string;
  /** Right-hand action controls (gear, refresh, etc.). Each action must have ≥44pt tap target. */
  actions?: React.ReactNode;
}

/**
 * Shared screen header: large title + optional right-actions slot.
 *
 * Handles the safe-area top inset so every screen gets one consistent
 * `insets.top + spacing.sm` treatment. Place as the first child of a
 * ScrollView's content (not outside it) so the top space scrolls naturally.
 */
export function ScreenHeader({ title, actions }: ScreenHeaderProps) {
  const { colors } = useTheme();
  const insets = useSafeAreaInsets();

  return (
    <View
      style={[styles.container, { paddingTop: insets.top + spacing.sm }]}
    >
      <Text
        style={[styles.title, { color: colors.text }]}
        accessibilityRole="header"
      >
        {title}
      </Text>
      {actions ? <View style={styles.actions}>{actions}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    paddingHorizontal: spacing.base,
    paddingBottom: spacing.xs,
  },
  title: {
    fontSize: typeScale.largeTitle,
    fontWeight: "700",
  },
  actions: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
  },
});
