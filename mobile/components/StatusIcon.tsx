import { StyleSheet, Text } from "react-native";

import { statusAccessibilityLabel, type TodayEntry } from "@/state/today";

/**
 * Compact status/evidence indicator for a timeline entry. Uses a glyph paired
 * with an accessibility label so screen-reader users get the same information
 * sighted users read from the icon (coding standard: evidence/status use icons
 * with accessibility labels).
 */
export function StatusIcon({ entry }: { entry: TodayEntry }) {
  const glyph = iconFor(entry);
  return (
    <Text
      style={styles.icon}
      accessibilityRole="image"
      accessibilityLabel={statusAccessibilityLabel(entry)}
    >
      {glyph}
    </Text>
  );
}

function iconFor(entry: TodayEntry): string {
  if (entry.status === "pending") {
    return "…";
  }
  return entry.sourceBacked ? "✓" : "≈";
}

const styles = StyleSheet.create({
  icon: {
    fontSize: 18,
    color: "#3A3A3C",
    width: 24,
    textAlign: "center",
  },
});
