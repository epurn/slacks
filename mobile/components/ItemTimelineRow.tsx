import { Animated, Pressable, StyleSheet, Text, View } from "react-native";

import type { DerivedItem } from "@/api/derivedItems";
import { ProvenanceIcon, Skeleton } from "@/components/ui";
import { useTheme, spacing, typeScale, radius } from "@/theme";
import { useResolveFade } from "@/theme/motion";

function formatKcal(n: number | null): string {
  if (n === null) return "—";
  return `${Math.round(n)} kcal`;
}

type ItemTimelineRowProps =
  | {
      /** True while the event is pending/processing — no resolved item yet. */
      loading: true;
      /** Screen-reader label conveying the in-progress status (e.g. "Estimating"). */
      accessibilityLabel: string;
    }
  | {
      loading?: false;
      item: DerivedItem;
      /** True when the parent log event is needs_clarification. */
      needsClarification?: boolean;
      /** True for an uncounted label proposal awaiting confirm (FTY-196/197). */
      proposal?: boolean;
      onPress?: () => void;
      /**
       * Beat 1 — entry resolve (FTY-181). When true, the row eases its value in
       * once (shimmer → value) with `gentleSpring` (a simple fade under Reduce
       * Motion). Set only for a genuine pending→resolved transition, never on
       * initial mount, so the app does not fade every row on load. The timeline
       * keys the first resolved row by the same event id the pending skeleton
       * used, so this fade plays on that reused instance — the shimmer resolves
       * into the value in place (FTY-180), never a swap between differently-keyed
       * rows.
       */
      animateResolve?: boolean;
    };

/**
 * A single derived item row in the Today timeline (FTY-098).
 *
 * Shows: name · kcal · always-on source icon (FTY-092 provenance).
 * "needs a detail" (needs_clarification parent) entries render muted with a
 * gentle inline tag and are visibly uncounted — they do not appear in hero
 * figures per the finalized-state filter, so no extra math needed here.
 * A `proposal` row (FTY-197) is a legible label parse held uncounted (FTY-196):
 * it shows its parsed kcal but muted, tagged "not counted", and invites a tap to
 * confirm — honestly surfaced, never silently counted.
 * Tapping calls `onPress` (opens the detail / confirm sheet).
 *
 * `loading` drives the "thinking" state (FTY-180): a pending/processing entry
 * with no resolved item yet renders a `Skeleton` shimmer in the exact same
 * container geometry (row height, insets, icon slot, kcal column width) this
 * component uses once resolved, so the row never jumps or reflows when the
 * estimate lands — the values simply fade in over the placeholder's footprint
 * (the entry-resolve beat, FTY-181).
 */
export function ItemTimelineRow(props: ItemTimelineRowProps) {
  const { colors } = useTheme();
  // Called unconditionally (rules-of-hooks): the loading branch returns early
  // below, but a reused instance transitions loading→resolved in place, so this
  // arms the entry-resolve fade (beat 1) for that transition (FTY-180/181).
  const fadeOpacity = useResolveFade(
    props.loading !== true && props.animateResolve === true,
  );

  if (props.loading) {
    return (
      <View
        style={[styles.row, { borderBottomColor: colors.separator }]}
        accessibilityRole="progressbar"
        accessibilityLabel={props.accessibilityLabel}
      >
        <View style={styles.iconSlot}>
          <Skeleton
            width={16}
            height={16}
            borderRadius={8}
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
          />
        </View>
        <Skeleton
          width="55%"
          height={16}
          borderRadius={radius.sm}
          style={styles.nameSkeleton}
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
        />
        <Skeleton
          width={64}
          height={16}
          borderRadius={radius.sm}
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
        />
      </View>
    );
  }

  const { item, needsClarification = false, proposal = false, onPress } = props;

  const name = item.name;
  const kcal =
    item.item_type === "food" ? item.calories : item.active_calories;
  const source = item.item_type === "food" ? item.source : null;
  const is_edited = item.is_edited ?? false;

  // Both uncounted states render muted; only their tag / kcal treatment differ.
  const uncounted = needsClarification || proposal;
  const textColor = uncounted ? colors.textMuted : colors.text;
  const kcalColor = uncounted ? colors.textMuted : colors.textSecondary;

  const a11yLabel = needsClarification
    ? `${name}, needs a detail, uncounted`
    : proposal
      ? `${name}, ${kcal !== null ? Math.round(kcal) : 0} kcal, not yet counted`
      : item.item_type === "food"
        ? `${name}, ${kcal !== null ? Math.round(kcal) : 0} kcal`
        : `${name}, ${kcal !== null ? Math.round(kcal) : 0} kcal burned`;

  const a11yHint = needsClarification
    ? "Tap to add the missing detail"
    : proposal
      ? "Tap to confirm before it counts"
      : "Tap to view details";

  return (
    <Animated.View style={{ opacity: fadeOpacity }}>
      <Pressable
        style={({ pressed }) => [
          styles.row,
          { borderBottomColor: colors.separator },
          pressed && { opacity: 0.7 },
        ]}
        onPress={onPress}
        accessibilityRole="button"
        accessibilityLabel={a11yLabel}
        accessibilityHint={a11yHint}
      >
        {/* Provenance icon — always on */}
        <ProvenanceIcon source={source} is_edited={is_edited} />

        {/* Name */}
        <Text
          style={[styles.name, { color: textColor }]}
          numberOfLines={1}
          accessibilityElementsHidden
        >
          {name}
        </Text>

        {/* Uncounted tag: "needs a detail" (clarify) or "not counted" (proposal) */}
        {uncounted ? (
          <View
            style={[styles.needsDetailTag, { backgroundColor: colors.controlBackground }]}
            accessibilityElementsHidden
          >
            <Text style={[styles.needsDetailText, { color: colors.textMuted }]}>
              {needsClarification ? "needs a detail" : "not counted"}
            </Text>
          </View>
        ) : null}

        {/* Kcal — right-aligned. A proposal shows its parsed kcal (muted); a
            needs-a-detail row has no value yet, so it shows an em dash. */}
        <Text
          style={[styles.kcal, { color: kcalColor }]}
          accessibilityElementsHidden
        >
          {needsClarification ? "—" : formatKcal(kcal)}
        </Text>
      </Pressable>
    </Animated.View>
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
  // Matches ProvenanceIcon's own `icon` style width so the loading skeleton's
  // icon dot lands in the exact same slot the resolved provenance icon fills.
  iconSlot: {
    width: 22,
    alignItems: "center",
  },
  nameSkeleton: {
    flex: 1,
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
