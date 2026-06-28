import { Pressable, StyleSheet, Text, View } from "react-native";

import type { DerivedItem } from "@/api/derivedItems";
import { SourceIcon } from "@/components/SourceIcon";
import { useTheme, spacing, typeScale, radius } from "@/theme";

function formatKcal(n: number | null): string {
  if (n === null) return "—";
  return `${Math.round(n)} kcal`;
}

/**
 * A single derived item row in the Today timeline (FTY-098).
 *
 * Shows: name · kcal · always-on source icon (FTY-092 provenance).
 * "needs a detail" (needs_clarification parent) entries render muted with a
 * gentle inline tag and are visibly uncounted — they do not appear in hero
 * figures per the finalized-state filter, so no extra math needed here.
 * Tapping calls `onPress` (stub for FTY-100 detail sheet).
 */
export function ItemTimelineRow({
  item,
  needsClarification = false,
  onPress,
}: {
  item: DerivedItem;
  /** True when the parent log event is needs_clarification. */
  needsClarification?: boolean;
  onPress?: () => void;
}) {
  const { colors } = useTheme();

  const name = item.name;
  const kcal =
    item.item_type === "food" ? item.calories : item.active_calories;
  const source = item.item_type === "food" ? item.source : null;
  const is_edited = item.is_edited ?? false;

  const textColor = needsClarification ? colors.textMuted : colors.text;
  const kcalColor = needsClarification ? colors.textMuted : colors.textSecondary;

  const a11yLabel = needsClarification
    ? `${name}, needs a detail, uncounted`
    : item.item_type === "food"
      ? `${name}, ${kcal !== null ? Math.round(kcal) : 0} kcal`
      : `${name}, ${kcal !== null ? Math.round(kcal) : 0} kcal burned`;

  return (
    <Pressable
      style={({ pressed }) => [
        styles.row,
        { borderBottomColor: colors.separator },
        pressed && { opacity: 0.7 },
      ]}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={a11yLabel}
      accessibilityHint={needsClarification ? "Tap to add the missing detail" : "Tap to view details"}
    >
      {/* Source icon — always on */}
      <SourceIcon source={source} is_edited={is_edited} />

      {/* Name */}
      <Text
        style={[styles.name, { color: textColor }]}
        numberOfLines={1}
        accessibilityElementsHidden
      >
        {name}
      </Text>

      {/* "needs a detail" tag */}
      {needsClarification ? (
        <View
          style={[styles.needsDetailTag, { backgroundColor: colors.controlBackground }]}
          accessibilityElementsHidden
        >
          <Text style={[styles.needsDetailText, { color: colors.textMuted }]}>
            needs a detail
          </Text>
        </View>
      ) : null}

      {/* Kcal — right-aligned */}
      <Text
        style={[styles.kcal, { color: kcalColor }]}
        accessibilityElementsHidden
      >
        {needsClarification ? "—" : formatKcal(kcal)}
      </Text>
    </Pressable>
  );
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
  needsDetailTag: {
    borderRadius: radius.sm,
    paddingHorizontal: spacing.sm,
    paddingVertical: 2,
  },
  needsDetailText: {
    fontSize: typeScale.caption2,
    fontWeight: "500",
  },
  kcal: {
    fontSize: typeScale.callout,
    fontVariant: ["tabular-nums"],
    minWidth: 64,
    textAlign: "right",
  },
});
