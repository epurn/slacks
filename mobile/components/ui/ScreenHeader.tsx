import { StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";

import { spacing } from "@/theme";
import { DisplayText } from "./DisplayText";

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
 *
 * Horizontal padding is intentionally inherited from that content container
 * (which already applies `paddingHorizontal: spacing.base`) so the title and
 * actions align with the body below; the header must not add its own, or it
 * would be double-indented relative to the content.
 */
export function ScreenHeader({ title, actions }: ScreenHeaderProps) {
  const insets = useSafeAreaInsets();

  return (
    <View
      style={[styles.container, { paddingTop: insets.top + spacing.sm }]}
    >
      <DisplayText scale="largeTitle" accessibilityRole="header">
        {title}
      </DisplayText>
      {actions ? <View style={styles.actions}>{actions}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    // No paddingHorizontal: inherited from the host content container so the
    // title/actions align with the body (see component doc).
    paddingBottom: spacing.xs,
  },
  actions: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.xs,
  },
});
