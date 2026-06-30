import { StyleSheet, Text, View } from "react-native";

import type { OutboxSyncState } from "@/state/outbox";
import { spacing, typeScale, useTheme } from "@/theme";

/**
 * A dedicated offline-queued timeline row (FTY-147).
 *
 * Offline captures render through this row — never an offline branch inside
 * {@link EntryRow}, which carries the FTY-148 tappable-correction and FTY-149
 * needs-clarification behaviour that an offline variant would collide with. The
 * row is deliberately its own calm, uncounted, non-tappable type: the raw text
 * the user captured plus an explicit offline indicator carried **in words**
 * (never colour alone), and **no fabricated number** — an offline entry is
 * uncounted until the server resolves it on reconnect.
 *
 * It sits in the same timeline card as online rows so the layout never shifts
 * when the entry later drains and folds into the normal server-driven flow.
 */
export function OfflineEntryRow({
  rawText,
  state,
}: {
  rawText: string;
  state: OutboxSyncState;
}) {
  const { colors } = useTheme();
  const indicator = offlineIndicator(state);

  return (
    <View
      style={[styles.row, { borderBottomColor: colors.separator }]}
      accessible
      accessibilityLabel={`${rawText}, ${indicator.a11y}`}
    >
      <Text
        style={[styles.name, { color: colors.text }]}
        numberOfLines={1}
        accessibilityElementsHidden
      >
        {rawText}
      </Text>
      <View style={styles.indicator} accessibilityElementsHidden>
        <Text style={[styles.glyph, { color: colors.textMuted }]}>
          {indicator.glyph}
        </Text>
        <Text style={[styles.label, { color: colors.textMuted }]} numberOfLines={1}>
          {indicator.label}
        </Text>
      </View>
    </View>
  );
}

/**
 * Calm presentation for the offline indicator, by local sync state. The state is
 * always carried in words (never colour alone), and no kcal/macro value is ever
 * shown — an offline-queued entry is uncounted until the server resolves it.
 */
function offlineIndicator(state: OutboxSyncState): {
  readonly glyph: string;
  readonly label: string;
  readonly a11y: string;
} {
  switch (state) {
    case "submitting":
      return { glyph: "⟳", label: "Sending…", a11y: "sending" };
    case "failed":
      return { glyph: "!", label: "Couldn't send", a11y: "couldn't send" };
    case "queued":
    case "accepted":
    default:
      return {
        glyph: "⇡",
        label: "Offline — queued",
        a11y: "offline, queued to send",
      };
  }
}

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.md,
    paddingHorizontal: spacing.base,
    borderBottomWidth: StyleSheet.hairlineWidth,
    minHeight: 44,
  },
  name: {
    flex: 1,
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  indicator: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
  },
  glyph: {
    fontSize: typeScale.footnote,
    fontWeight: "600",
  },
  label: {
    fontSize: typeScale.footnote,
  },
});
