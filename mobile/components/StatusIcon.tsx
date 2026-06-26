import { StyleSheet, Text } from "react-native";

import type { LogEventStatus } from "@/api/logEvents";
import { statusPresentation } from "@/state/today";

/**
 * Compact status indicator for a timeline entry. Pairs a glyph with an
 * accessibility label so screen-reader users get the same status sighted users
 * read from the icon (coding standard: status uses icons with accessibility
 * labels).
 */
export function StatusIcon({ status }: { status: LogEventStatus }) {
  const { glyph, accessibilityLabel } = statusPresentation(status);
  return (
    <Text
      style={styles.icon}
      accessibilityRole="image"
      accessibilityLabel={accessibilityLabel}
    >
      {glyph}
    </Text>
  );
}

const styles = StyleSheet.create({
  icon: {
    fontSize: 18,
    color: "#3A3A3C",
    width: 24,
    textAlign: "center",
  },
});
