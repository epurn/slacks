import { StyleSheet, Text } from "react-native";

import type { LogEventStatus } from "@/api/logEvents";
import { statusPresentation } from "@/state/today";
import { typeScale, useTheme } from "@/theme";

/**
 * Compact status indicator for a timeline entry. Pairs a glyph with an
 * accessibility label so screen-reader users get the same status sighted users
 * read from the icon (coding standard: status uses icons with accessibility
 * labels).
 *
 * Colour comes from the theme's `textSecondary` token, which meets WCAG AA
 * against every surface in both palettes (FTY-177) — the glyph must stay
 * legible on the dark charcoal surface, not the near-black it used to hardcode.
 */
export function StatusIcon({ status }: { status: LogEventStatus }) {
  const { colors } = useTheme();
  const { glyph, accessibilityLabel } = statusPresentation(status);
  return (
    <Text
      style={[styles.icon, { color: colors.textSecondary }]}
      accessibilityRole="image"
      accessibilityLabel={accessibilityLabel}
    >
      {glyph}
    </Text>
  );
}

const styles = StyleSheet.create({
  icon: {
    fontSize: typeScale.iconGlyph,
    width: 24,
    textAlign: "center",
  },
});
