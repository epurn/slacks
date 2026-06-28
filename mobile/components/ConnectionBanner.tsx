import { StyleSheet, Text, View } from "react-native";

import {
  connectionBannerPresentation,
  type ReachabilityState,
} from "@/state/reachability";
import { radius, spacing, typeScale, useTheme } from "@/theme";

/**
 * The calm connection-status banner (FTY-104).
 *
 * It reflects offline / reconnecting / queued state using the design tokens and
 * the calm tone from the UX doc (§6): a gentle, non-blocking note that capture
 * is queued and will send on reconnect. It never reads as an error or alarm
 * (no coral/error colour), never blocks capture, and is hidden entirely when the
 * app is online and caught up.
 *
 * Accessibility: the state is conveyed in words (the same string used as the
 * accessibility label and announced via `role="status"`), so it never relies on
 * colour alone. A muted left bar plus the leading "Offline ·" / "Reconnecting"
 * text carry the meaning for colour-blind and VoiceOver users alike.
 */
export function ConnectionBanner({
  state,
  queuedCount,
}: {
  state: ReachabilityState;
  queuedCount: number;
}) {
  const { colors } = useTheme();
  const presentation = connectionBannerPresentation(state, queuedCount);

  if (!presentation.visible) return null;

  const accentColor =
    presentation.tone === "accent" ? colors.accentText : colors.textSecondary;

  return (
    <View
      accessible
      accessibilityRole="text"
      accessibilityLiveRegion="polite"
      accessibilityLabel={presentation.label}
      style={[
        styles.banner,
        { backgroundColor: colors.surfaceRaised, borderColor: colors.separator },
      ]}
    >
      <View style={[styles.accentBar, { backgroundColor: accentColor }]} />
      <Text style={[styles.label, { color: colors.textSecondary }]}>
        {presentation.label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    borderRadius: radius.md,
    borderWidth: StyleSheet.hairlineWidth,
    paddingVertical: spacing.sm,
    paddingHorizontal: spacing.md,
    marginBottom: spacing.md,
  },
  accentBar: {
    width: 3,
    alignSelf: "stretch",
    borderRadius: 2,
  },
  label: {
    flex: 1,
    fontSize: typeScale.footnote,
    fontWeight: "500",
  },
});
