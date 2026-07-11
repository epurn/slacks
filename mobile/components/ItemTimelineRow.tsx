import {
  Animated,
  Pressable,
  StyleSheet,
  Text,
  useWindowDimensions,
  View,
  type AccessibilityActionEvent,
} from "react-native";

import type { DerivedItem } from "@/api/derivedItems";
import { ProvenanceIcon, provenancePresentation, Skeleton } from "@/components/ui";
import { useTheme, spacing, typeScale, radius } from "@/theme";
import { useResolveFade } from "@/theme/motion";

/**
 * Content-size threshold at/above which the row reflows the inline tag and the
 * kcal column onto a second line beneath the name/question (FTY-360). RN's
 * `fontScale` mirrors the active iOS content-size category: standard Dynamic
 * Type tops out at xxxLarge (~1.35), and the first "Larger Accessibility" size
 * (accessibilityMedium) jumps to ~1.65. A 1.5 cutoff therefore cleanly divides
 * standard sizes — which keep the single horizontal line, unchanged — from the
 * accessibility sizes, where a lone horizontal line starves the flexed
 * name/question column below a legible word width and wrapping text collapses to
 * one glyph per line. Driven off the system content-size signal, never a
 * hardcoded device width.
 */
const AX_REFLOW_FONT_SCALE = 1.5;

// Left indent for the reflowed second line so the tag/kcal align under the
// name column rather than under the provenance icon (icon slot width + row gap).
const STACKED_SECONDARY_INDENT = 22 + spacing.sm;

function formatKcal(n: number | null): string {
  if (n === null) return "—";
  return `${Math.round(n)} kcal`;
}

function kcalOf(item: DerivedItem): number | null {
  return item.item_type === "food" ? item.calories : item.active_calories;
}

function totalKcal(items: readonly DerivedItem[]): number | null {
  let total = 0;
  for (const item of items) {
    const kcal = kcalOf(item);
    if (kcal === null) return null;
    total += kcal;
  }
  return total;
}

type ItemTimelineRowProps =
  | {
      /** True while the event is pending/processing — no resolved item yet. */
      loading: true;
      /** Screen-reader label conveying the in-progress status (e.g. "Estimating"). */
      accessibilityLabel: string;
      /**
       * Delete custom action (FTY-322) for a server-backed row that is still
       * estimating — deletable like any other server row. Supplied by the swipe
       * wrapper and attached to the loading row's own accessible element so
       * VoiceOver can delete without the pointer-only gesture.
       */
      accessibilityActions?: readonly { name: string; label: string }[];
      onAccessibilityAction?: (event: AccessibilityActionEvent) => void;
      /** Stable row id for E2E checks that assert the skeleton resolves in place. */
      testID?: string;
    }
  | {
      loading?: false;
      item: DerivedItem;
      /**
       * Additional derived items for the same log event, summarized into this
       * one row during a fresh pending→resolved transition so the timeline does
       * not grow from one skeleton into several item-keyed rows.
       */
      additionalItems?: readonly DerivedItem[];
      /** True when the parent log event is needs_clarification. */
      needsClarification?: boolean;
      /** True for an uncounted label proposal awaiting confirm (FTY-196/197). */
      proposal?: boolean;
      onPress?: () => void;
      /**
       * Read-only mode for the past-day timeline (FTY-199). The same row, but
       * rendered as a non-interactive element — no tap affordance, no correction
       * sheet — because a historical day is view-only (editing past entries is a
       * non-goal). It stays fully legible and its VoiceOver label carries the
       * value *and* its provenance, so a source is still conveyed at a glance and
       * to a screen reader; there is simply no false "tap to edit" affordance.
       * Default off, so Today's interactive rows are unchanged.
       */
      readOnly?: boolean;
      /**
       * Delete custom action (FTY-322), supplied by the swipe wrapper so the
       * destructive Delete stays reachable by VoiceOver on this row's own
       * accessible element — the swipe gesture is pointer-only. Spread onto the
       * interactive Pressable; absent (and inert) for the read-only past-day row,
       * which is not deletable.
       */
      accessibilityActions?: readonly { name: string; label: string }[];
      onAccessibilityAction?: (event: AccessibilityActionEvent) => void;
      /** Stable row id for E2E checks that assert the value resolves in place. */
      testID?: string;
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
  // Reflow to a stacked (two-line) layout at the Larger Accessibility content
  // sizes so the tag/kcal never squeeze the name/question column below a legible
  // word width (FTY-360). Read from the live system content-size signal.
  const { fontScale } = useWindowDimensions();
  const stacked = fontScale >= AX_REFLOW_FONT_SCALE;
  // Called unconditionally (rules-of-hooks): the loading branch returns early
  // below, but a reused instance transitions loading→resolved in place, so this
  // arms the entry-resolve fade (beat 1) for that transition (FTY-180/181).
  const fadeOpacity = useResolveFade(
    props.loading !== true && props.animateResolve === true,
    props.loading === true,
  );

  if (props.loading) {
    const iconSkeleton = (
      <View style={styles.iconSlot}>
        <Skeleton
          width={16}
          height={16}
          borderRadius={8}
          accessibilityElementsHidden
          importantForAccessibility="no-hide-descendants"
        />
      </View>
    );
    const nameSkeleton = (
      <Skeleton
        width="55%"
        height={16}
        borderRadius={radius.sm}
        style={styles.nameSkeleton}
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
      />
    );
    const kcalSkeleton = (
      <Skeleton
        width={64}
        height={16}
        borderRadius={radius.sm}
        accessibilityElementsHidden
        importantForAccessibility="no-hide-descendants"
      />
    );
    return (
      <View
        testID={props.testID}
        style={[styles.row, stacked && styles.rowStacked, { borderBottomColor: colors.separator }]}
        accessible
        accessibilityRole="progressbar"
        accessibilityLabel={props.accessibilityLabel}
        accessibilityActions={props.accessibilityActions}
        onAccessibilityAction={props.onAccessibilityAction}
      >
        {stacked ? (
          <>
            {/* Same skeleton footprint as the resolved stacked row, so the
                pending row still resolves in place without a jump at AX sizes. */}
            <View style={styles.stackedPrimary}>
              {iconSkeleton}
              {nameSkeleton}
            </View>
            <View style={styles.stackedSecondary}>{kcalSkeleton}</View>
          </>
        ) : (
          <>
            {iconSkeleton}
            {nameSkeleton}
            {kcalSkeleton}
          </>
        )}
      </View>
    );
  }

  const {
    item,
    additionalItems = [],
    needsClarification = false,
    proposal = false,
    onPress,
    testID,
    readOnly = false,
    accessibilityActions,
    onAccessibilityAction,
  } = props;
  const allItems = additionalItems.length > 0
    ? [item, ...additionalItems]
    : [item];
  const additionalCount = allItems.length - 1;

  const name = item.name;
  const kcal = totalKcal(allItems);
  const source = item.item_type === "food" ? item.source : null;
  const is_edited = item.is_edited ?? false;
  const displayName = additionalCount > 0 ? `${name} + ${additionalCount}` : name;

  // Both uncounted states render muted; only their tag / kcal treatment differ.
  const uncounted = needsClarification || proposal;
  const textColor = uncounted ? colors.textMuted : colors.text;
  const kcalColor = uncounted ? colors.textMuted : colors.textSecondary;

  const labelName =
    additionalCount > 0
      ? `${name} and ${additionalCount} more ${
          additionalCount === 1 ? "item" : "items"
        }`
      : name;
  const allExercise = allItems.every((row) => row.item_type === "exercise");
  const kcalLabel = `${kcal !== null ? Math.round(kcal) : 0} kcal${
    allExercise ? " burned" : additionalCount > 0 ? " total" : ""
  }`;
  const a11yLabel = needsClarification
    ? `${labelName}, needs a detail, uncounted`
    : proposal
      ? `${name}, ${kcal !== null ? Math.round(kcal) : 0} kcal, not yet counted`
      : `${labelName}, ${kcalLabel}`;

  const a11yHint = needsClarification
    ? "Tap to add the missing detail"
    : proposal
      ? "Tap to confirm before it counts"
      : "Tap to view details";

  // Provenance icon — always on.
  const iconNode = <ProvenanceIcon source={source} is_edited={is_edited} />;

  // Name. A resolved/proposal row is a single value line and stays clamped to
  // one line (name · kcal · source). A needs-a-detail row's name is the open
  // component's *question* text (FTY-330) — the row's primary content, not a
  // label beside a value — so it wraps to as many lines as it needs instead of
  // clipping to "How much hum…", which stays legible as the question grows and
  // under Dynamic Type.
  const nameNode = (
    <Text
      style={[styles.name, { color: textColor }]}
      numberOfLines={needsClarification ? undefined : 1}
      accessibilityElementsHidden
    >
      {displayName}
    </Text>
  );

  // Uncounted tag: "needs a detail" (clarify) or "not counted" (proposal).
  const tagNode = uncounted ? (
    <View
      style={[styles.needsDetailTag, { backgroundColor: colors.controlBackground }]}
      accessibilityElementsHidden
    >
      <Text style={[styles.needsDetailText, { color: colors.textMuted }]}>
        {needsClarification ? "needs a detail" : "not counted"}
      </Text>
    </View>
  ) : null;

  // Kcal — right-aligned. A proposal shows its parsed kcal (muted); a
  // needs-a-detail row has no value yet, so it shows an em dash.
  const kcalNode = (
    <Text
      style={[styles.kcal, stacked && styles.kcalStacked, { color: kcalColor }]}
      accessibilityElementsHidden
    >
      {needsClarification ? "—" : formatKcal(kcal)}
    </Text>
  );

  // The row's inner content is identical whether the row is interactive (Today)
  // or read-only (a past day) — only the wrapping element and its accessibility
  // treatment differ, so the two paths never drift visually.
  //
  // At standard Dynamic Type the four slots sit on one horizontal line exactly
  // as before. At the Larger Accessibility sizes (`stacked`), the tag and kcal
  // reflow to a second line so the flexed name/question column can use the full
  // row width and wrap by word instead of collapsing to one glyph per line
  // (FTY-360).
  const rowContent = stacked ? (
    <>
      <View style={styles.stackedPrimary}>
        {iconNode}
        {nameNode}
      </View>
      <View style={styles.stackedSecondary}>
        {tagNode}
        {kcalNode}
      </View>
    </>
  ) : (
    <>
      {iconNode}
      {nameNode}
      {tagNode}
      {kcalNode}
    </>
  );

  // Read-only (FTY-199): render the value as a single, non-interactive
  // accessibility element. No `button` role and no "tap to…" hint (there is
  // nothing to tap on a view-only past day), but the label still carries the
  // value *and* its provenance so a screen reader hears the source at a glance.
  if (readOnly) {
    const provenanceLabel = provenancePresentation(source, is_edited).accessibilityLabel;
    return (
      <View
        testID={testID}
        style={[styles.row, stacked && styles.rowStacked, { borderBottomColor: colors.separator }]}
        accessible
        accessibilityLabel={`${a11yLabel}, ${provenanceLabel}`}
      >
        {rowContent}
      </View>
    );
  }

  return (
    <Animated.View style={{ opacity: props.animateResolve === true ? fadeOpacity : 1 }}>
      <Pressable
        testID={testID}
        style={({ pressed }) => [
          styles.row,
          stacked && styles.rowStacked,
          { borderBottomColor: colors.separator },
          pressed && { opacity: 0.7 },
        ]}
        onPress={onPress}
        accessibilityRole="button"
        accessibilityLabel={a11yLabel}
        accessibilityHint={a11yHint}
        accessibilityActions={accessibilityActions}
        onAccessibilityAction={onAccessibilityAction}
      >
        {rowContent}
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
  // FTY-360: at the Larger Accessibility sizes the row becomes a vertical stack
  // (name/question line, then tag + kcal line) so the flexed text column can use
  // the full row width. Standard sizes never apply this — `styles.row` stays the
  // single horizontal line.
  rowStacked: {
    flexDirection: "column",
    alignItems: "stretch",
    gap: spacing.xs,
  },
  stackedPrimary: {
    flexDirection: "row",
    // Top-align the icon with the first line of the wrapping name/question.
    alignItems: "flex-start",
    gap: spacing.sm,
  },
  stackedSecondary: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    // Align the reflowed tag/kcal under the name column, not under the icon.
    paddingLeft: STACKED_SECONDARY_INDENT,
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
  // On the reflowed second line the kcal owns the row width and stays right
  // aligned; it no longer needs to reserve a fixed 64pt column beside the text.
  kcalStacked: {
    flex: 1,
  },
});
