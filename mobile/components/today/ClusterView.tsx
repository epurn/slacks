import { StyleSheet, Text, View } from "react-native";

import {
  type DerivedItem,
  type DerivedFoodItemDTO,
} from "@/api/derivedItems";
import { type LogEventDTO } from "@/api/logEvents";
import { EntryRow } from "@/components/EntryRow";
import { ItemTimelineRow } from "@/components/ItemTimelineRow";
import { OfflineEntryRow } from "@/components/OfflineEntryRow";
import { type OutboxSyncState } from "@/state/outbox";
import { formatWallClockTime, statusPresentation } from "@/state/today";
import { useTheme, spacing, typeScale, radius } from "@/theme";

import {
  isSyntheticSavedFoodItem,
  itemTimelineExtraRowTestID,
  itemTimelineRowTestID,
} from "./helpers";

/**
 * One time-anchored cluster card of timeline rows (FTY-031). Each event renders
 * through the row that matches its status: an offline-queued capture, a resolved
 * item-forward row, an uncounted label proposal, a needs-a-detail row, an
 * actionable failed row, or the pending→resolve skeleton that fades in place.
 */
export function ClusterView({
  cluster,
  itemsByEvent,
  offlineStateById,
  resolveAnimIds,
  onOpenItem,
  onOpenProposal,
  onOpenClarify,
  onRetryFailed,
  onEditFailedAsText,
  readOnly = false,
  colors,
}: {
  cluster: { anchorTime: string; events: readonly LogEventDTO[] };
  itemsByEvent: Readonly<Record<string, readonly DerivedItem[]>>;
  offlineStateById: ReadonlyMap<string, OutboxSyncState>;
  resolveAnimIds: ReadonlySet<string>;
  onOpenItem?: (item: DerivedItem, logPhrase: string) => void;
  onOpenProposal?: (item: DerivedFoodItemDTO) => void;
  onOpenClarify?: (event: LogEventDTO) => void;
  onRetryFailed?: (event: LogEventDTO) => void;
  onEditFailedAsText?: (event: LogEventDTO) => void;
  /**
   * Read-only past-day timeline (FTY-199): render the same rows non-interactively
   * (no correction/clarify/retry affordances) because a historical day is
   * view-only. Today leaves this off and passes the handlers as usual.
   */
  readOnly?: boolean;
  colors: ReturnType<typeof useTheme>["colors"];
}) {
  return (
    <View style={styles.cluster}>
      <Text style={[styles.clusterTime, { color: colors.textMuted }]}>
        {formatWallClockTime(cluster.anchorTime)}
      </Text>
      <View style={[styles.card, { backgroundColor: colors.surfaceRaised }]}>
        {cluster.events.map((event) => {
          // An offline-queued capture renders through its own dedicated row —
          // never an offline branch inside EntryRow (FTY-147). It is calm,
          // uncounted, non-tappable: raw text + an explicit offline indicator.
          const offlineState = offlineStateById.get(event.id);
          if (offlineState) {
            return (
              <OfflineEntryRow
                key={event.id}
                rawText={event.raw_text}
                state={offlineState}
              />
            );
          }

          const items = itemsByEvent[event.id] ?? [];

          // Completed items are item-forward: proposed rows reopen confirm,
          // resolved rows open correction. Fresh multi-item resolves briefly
          // summarize extras until the marker clears.
          if (event.status === "completed" && items.length > 0) {
            // Beat 1 — only genuine pending→resolved counted rows animate.
            const animateResolve = resolveAnimIds.has(event.id);
            const rowTestID = itemTimelineRowTestID(event.id);
            if (animateResolve && items.length > 1) {
              const firstItem = items[0];
              if (!firstItem) return null;
              return firstItem.item_type === "food" && firstItem.status === "proposed" ? (
                <ItemTimelineRow
                  key={event.id}
                  item={firstItem}
                  proposal
                  onPress={onOpenProposal ? () => onOpenProposal(firstItem) : undefined}
                  readOnly={readOnly}
                  testID={rowTestID}
                />
              ) : (
                <ItemTimelineRow
                  key={event.id}
                  item={firstItem}
                  additionalItems={items.slice(1)}
                  needsClarification={false}
                  onPress={onOpenItem ? () => onOpenItem(firstItem, event.raw_text) : undefined}
                  readOnly={readOnly}
                  animateResolve
                  testID={rowTestID}
                />
              );
            }
            return items.map((item, index) => {
              const key = index === 0 ? event.id : item.id;
              const testID =
                index === 0
                  ? rowTestID
                  : itemTimelineExtraRowTestID(event.id, item.id);
              return item.item_type === "food" && item.status === "proposed" ? (
                <ItemTimelineRow
                  key={key}
                  item={item}
                  proposal
                  onPress={onOpenProposal ? () => onOpenProposal(item) : undefined}
                  readOnly={readOnly}
                  testID={testID}
                />
              ) : (
                <ItemTimelineRow
                  key={key}
                  item={item}
                  needsClarification={false}
                  onPress={onOpenItem ? () => onOpenItem(item, event.raw_text) : undefined}
                  readOnly={readOnly}
                  animateResolve={animateResolve}
                  testID={testID}
                />
              );
            });
          }

          // Optimistic / saved-food synthetic items (before the server feed
          // reports the entry). Only true local saved-food rows render here
          // (FTY-053). A server-fed by-date item is never surfaced through this
          // fallback: it can only render via the completed branch above, so a
          // resolved value row always appears on the pending→completed
          // transition that resolves the skeleton in place (FTY-180) and arms
          // beat 1 (resolve animation + haptic, FTY-181) — never un-animated
          // because the by-date feed won the poll race against the event-list
          // poll, or the event-list poll failed (FTY-181 review).
          const syntheticItems = items.filter(isSyntheticSavedFoodItem);
          if (syntheticItems.length > 0) {
            return syntheticItems.map((item) => (
              <ItemTimelineRow
                key={item.id}
                item={item}
                needsClarification={false}
                onPress={onOpenItem ? () => onOpenItem(item, event.raw_text) : undefined}
                readOnly={readOnly}
                testID={itemTimelineExtraRowTestID(event.id, item.id)}
              />
            ));
          }

          // needs_clarification → legible, inviting "needs a detail" row whose
          // tap opens the clarify-mode sheet (FTY-149).
          if (event.status === "needs_clarification") {
            return (
              <EntryRow
                key={event.id}
                event={event}
                onPress={onOpenClarify ? () => onOpenClarify(event) : undefined}
                readOnly={readOnly}
              />
            );
          }

          // failed → calm, actionable "couldn't read that" row with Retry +
          // Edit as text; never a static dead-end (FTY-176).
          if (event.status === "failed") {
            return (
              <EntryRow
                key={event.id}
                event={event}
                onRetry={onRetryFailed ? () => onRetryFailed(event) : undefined}
                onEditAsText={
                  onEditFailedAsText ? () => onEditFailedAsText(event) : undefined
                }
                readOnly={readOnly}
              />
            );
          }

          // pending / processing with no resolved item yet → the "thinking"
          // state: a Skeleton shimmer sized to the resolved ItemTimelineRow it
          // will become (FTY-180), so the row resolves in place with no
          // layout shift. Never the literal "Waiting"/"Estimating" text.
          if (event.status === "pending" || event.status === "processing") {
            return (
              <ItemTimelineRow
                key={event.id}
                loading
                accessibilityLabel={statusPresentation(event.status).accessibilityLabel}
                testID={itemTimelineRowTestID(event.id)}
              />
            );
          }

          // Freshly completed and still waiting on by-date items: hold the same
          // loading row. Items fade in; confirmed no-items falls through below.
          if (resolveAnimIds.has(event.id)) {
            return (
              <ItemTimelineRow
                key={event.id}
                loading
                accessibilityLabel={statusPresentation("processing").accessibilityLabel}
                testID={itemTimelineRowTestID(event.id)}
              />
            );
          }

          // completed with no items and no in-flight resolve — an entry already
          // completed on initial load, or the rare estimate that produced nothing
          // to show → terminal status placeholder, not a permanent shimmer.
          return <EntryRow key={event.id} event={event} />;
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  cluster: {
    marginBottom: spacing.sm,
  },
  clusterTime: {
    fontSize: typeScale.caption1,
    fontWeight: "500",
    marginBottom: spacing.xs,
    paddingHorizontal: spacing.xs,
  },
  card: {
    borderRadius: radius.lg,
    overflow: "hidden",
  },
});
