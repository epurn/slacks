import { useCallback, useState } from "react";
import {
  Animated,
  Pressable,
  StyleSheet,
  Text,
  View,
  type AccessibilityActionEvent,
} from "react-native";

import {
  type DerivedItem,
  type DerivedFoodItemDTO,
} from "@/api/derivedItems";
import { type LogEventDTO } from "@/api/logEvents";
import { formatAmount } from "@/components/correction/helpers";
import { AppIcon, ProvenanceIcon } from "@/components/ui";
import { useTheme, spacing, typeScale } from "@/theme";
import {
  useDisclosureReveal,
  useDisclosureRotation,
  useResolveFade,
} from "@/theme/motion";

import { mealDisplayName, sumItemKcal } from "./helpers";

/** Test id for the expanded breakdown container (expand assertions). */
function mealBreakdownTestID(eventId: string): string {
  return `meal-breakdown-${eventId}`;
}

/** Test id for one breakdown item row, keyed by the event and item id. */
function mealBreakdownItemTestID(eventId: string, itemId: string): string {
  return `meal-breakdown-${eventId}-${itemId}`;
}

function formatKcal(total: number | null): string {
  return total === null ? "—" : `${Math.round(total)} kcal`;
}

function kcalOf(item: DerivedItem): number | null {
  return item.item_type === "food" ? item.calories : item.active_calories;
}

/**
 * The portion + macro detail line for a breakdown row: the item's portion text
 * and, for a food item, its P/C/F grams (an exercise item has no macros, so it
 * shows the portion only). This is the per-item nutrition the collapsed meal row
 * summarizes — surfaced here so the breakdown shows each food, its portion, and
 * its calories/macros (FTY-420).
 */
function detailLine(item: DerivedItem): string {
  const portion = item.quantity_text;
  if (item.item_type === "exercise") return portion;
  const macros = `P ${formatAmount(item.protein_g)}g · C ${formatAmount(
    item.carbs_g,
  )}g · F ${formatAmount(item.fat_g)}g`;
  return `${portion} · ${macros}`;
}

/**
 * One item inside the expanded meal breakdown (FTY-420): the food/exercise
 * name, its provenance icon, its portion + calories/macros, and its energy —
 * a Pressable that opens the existing item edit / correction flow (a resolved
 * item → correction, a `proposed` food → the confirm sheet). Richer than the
 * collapsed timeline row on purpose: the breakdown is the detail view where the
 * user reads and corrects each component.
 */
function MealBreakdownRow({
  item,
  logPhrase,
  onOpenItem,
  onOpenProposal,
  readOnly,
  testID,
}: {
  item: DerivedItem;
  logPhrase: string;
  onOpenItem?: (item: DerivedItem, logPhrase: string) => void;
  onOpenProposal?: (item: DerivedFoodItemDTO) => void;
  readOnly: boolean;
  testID: string;
}) {
  const { colors } = useTheme();
  const proposed = item.item_type === "food" && item.status === "proposed";
  const source = item.item_type === "food" ? item.source : null;
  const kcal = kcalOf(item);
  const detail = detailLine(item);
  const kcalColor = proposed ? colors.textMuted : colors.textSecondary;
  const kcalSuffix = item.item_type === "exercise" ? " burned" : "";

  const a11yLabel = `${item.name}, ${detail}, ${
    kcal !== null ? Math.round(kcal) : 0
  } kcal${kcalSuffix}${proposed ? ", not yet counted" : ""}`;

  const onPress = proposed
    ? onOpenProposal
      ? () => onOpenProposal(item as DerivedFoodItemDTO)
      : undefined
    : onOpenItem
      ? () => onOpenItem(item, logPhrase)
      : undefined;

  const content = (
    <>
      <ProvenanceIcon source={source} is_edited={item.is_edited ?? false} />
      <View style={styles.detailColumn}>
        <Text
          style={[
            styles.itemName,
            { color: proposed ? colors.textMuted : colors.text },
          ]}
          numberOfLines={1}
          accessibilityElementsHidden
        >
          {item.name}
        </Text>
        <Text
          style={[styles.detailText, { color: colors.textMuted }]}
          numberOfLines={1}
          accessibilityElementsHidden
        >
          {proposed ? `${detail} · not counted` : detail}
        </Text>
      </View>
      <Text
        style={[styles.kcal, { color: kcalColor }]}
        accessibilityElementsHidden
      >
        {formatKcal(kcal)}
      </Text>
    </>
  );

  if (readOnly) {
    return (
      <View
        testID={testID}
        style={[styles.itemRow, { borderBottomColor: colors.separator }]}
        accessible
        accessibilityLabel={a11yLabel}
      >
        {content}
      </View>
    );
  }

  return (
    <Pressable
      testID={testID}
      style={({ pressed }) => [
        styles.itemRow,
        { borderBottomColor: colors.separator },
        pressed && { opacity: 0.7 },
      ]}
      onPress={onPress}
      accessibilityRole="button"
      accessibilityLabel={a11yLabel}
      accessibilityHint={
        proposed ? "Tap to confirm before it counts" : "Tap to edit this item"
      }
    >
      {content}
    </Pressable>
  );
}

/**
 * A composite-meal entry on the Today timeline (FTY-420): a multi-item
 * `log_event` rendered as **one collapsed row** — the event's model-generated
 * `name` (FTY-421/422, with a graceful raw-phrase fallback) and the summed meal
 * total — that expands on tap into the per-item breakdown, where every item
 * opens the existing item edit / correction flow.
 *
 * This replaces the older "one row per item" rendering for a multi-item meal: a
 * meal that logged as one natural-language phrase surfaces as one entry, not N
 * loose rows (operator dogfood 2026-07-20 §10 #6). The collapsed total is the
 * exact sum of the breakdown items, so it stays consistent after a per-item edit
 * re-costs one row. Expansion is a calm, native disclosure — the chevron rotates
 * and the breakdown fades in, both degrading to instant under Reduce Motion.
 */
export function MealEntryRow({
  event,
  items,
  animateResolve = false,
  onOpenItem,
  onOpenProposal,
  readOnly = false,
  testID,
  accessibilityActions,
  onAccessibilityAction,
}: {
  event: LogEventDTO;
  /** The meal's derived items (length ≥ 2 — a single-item entry is a plain row). */
  items: readonly DerivedItem[];
  /**
   * Beat 1 — entry resolve (FTY-181): fade the collapsed header in once on a
   * genuine pending→completed transition, so a multi-item meal resolves in place
   * from the skeleton with no layout shift. Never set on initial load.
   */
  animateResolve?: boolean;
  onOpenItem?: (item: DerivedItem, logPhrase: string) => void;
  onOpenProposal?: (item: DerivedFoodItemDTO) => void;
  /** Read-only past-day timeline (FTY-199): breakdown rows are non-interactive. */
  readOnly?: boolean;
  /** Event-keyed row id so the pending skeleton resolves into this header in place. */
  testID: string;
  /** Delete custom action (FTY-322), supplied by the swipe wrapper, on the header. */
  accessibilityActions?: readonly { name: string; label: string }[];
  onAccessibilityAction?: (event: AccessibilityActionEvent) => void;
}) {
  const { colors } = useTheme();
  const [expanded, setExpanded] = useState(false);
  const toggle = useCallback(() => setExpanded((prev) => !prev), []);

  const headerOpacity = useResolveFade(animateResolve, false);
  const chevronRotation = useDisclosureRotation(expanded);
  const breakdownOpacity = useDisclosureReveal(expanded);

  const title = mealDisplayName(event);
  const total = sumItemKcal(items);
  const a11yLabel = `${title}, ${total !== null ? Math.round(total) : 0} kcal total, ${
    items.length
  } items`;

  return (
    <View>
      <Animated.View style={{ opacity: animateResolve ? headerOpacity : 1 }}>
        <Pressable
          testID={testID}
          style={({ pressed }) => [
            styles.row,
            { borderBottomColor: colors.separator },
            pressed && { opacity: 0.7 },
          ]}
          onPress={toggle}
          accessibilityRole="button"
          accessibilityState={{ expanded }}
          accessibilityLabel={a11yLabel}
          accessibilityHint={
            expanded
              ? "Tap to collapse the breakdown"
              : "Tap to expand the per-item breakdown"
          }
          accessibilityActions={accessibilityActions}
          onAccessibilityAction={onAccessibilityAction}
        >
          <Animated.View
            style={[styles.chevron, { transform: [{ rotate: chevronRotation }] }]}
            accessibilityElementsHidden
            importantForAccessibility="no-hide-descendants"
          >
            <AppIcon name="chevron.forward" size={14} color={colors.textMuted} />
          </Animated.View>
          <Text
            style={[styles.name, { color: colors.text }]}
            numberOfLines={1}
            accessibilityElementsHidden
          >
            {title}
          </Text>
          <Text
            style={[styles.kcal, { color: colors.textSecondary }]}
            accessibilityElementsHidden
          >
            {formatKcal(total)}
          </Text>
        </Pressable>
      </Animated.View>

      {expanded ? (
        <Animated.View
          testID={mealBreakdownTestID(event.id)}
          style={{ opacity: breakdownOpacity }}
        >
          {items.map((item) => (
            <MealBreakdownRow
              key={item.id}
              item={item}
              logPhrase={event.raw_text}
              onOpenItem={onOpenItem}
              onOpenProposal={onOpenProposal}
              readOnly={readOnly}
              testID={mealBreakdownItemTestID(event.id, item.id)}
            />
          ))}
        </Animated.View>
      ) : null}
    </View>
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
  // Matches ItemTimelineRow's provenance-icon slot width so the meal title and
  // its breakdown rows' names align to the same left column.
  chevron: {
    width: 22,
    alignItems: "center",
  },
  name: {
    flex: 1,
    fontSize: typeScale.callout,
    fontWeight: "600",
  },
  kcal: {
    fontSize: typeScale.callout,
    fontVariant: ["tabular-nums"],
    minWidth: 64,
    textAlign: "right",
  },
  // Breakdown item rows sit under the collapsed header, indented one icon slot
  // so the disclosure chevron reads as their parent.
  itemRow: {
    flexDirection: "row",
    alignItems: "center",
    gap: spacing.sm,
    paddingVertical: spacing.sm,
    paddingLeft: spacing.base + spacing.md,
    paddingRight: spacing.base,
    borderBottomWidth: StyleSheet.hairlineWidth,
    minHeight: 44,
  },
  detailColumn: {
    flex: 1,
    gap: 2,
  },
  itemName: {
    fontSize: typeScale.callout,
    fontWeight: "500",
  },
  detailText: {
    fontSize: typeScale.caption1,
    fontVariant: ["tabular-nums"],
  },
});
