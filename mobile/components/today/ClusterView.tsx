import { type ReactNode } from "react";
import { StyleSheet, Text, View } from "react-native";

import {
  type DerivedItem,
  type DerivedFoodItemDTO,
} from "@/api/derivedItems";
import {
  type ClarificationQuestionDTO,
  type LogEventDTO,
} from "@/api/logEvents";
import { EntryRow } from "@/components/EntryRow";
import { ItemTimelineRow } from "@/components/ItemTimelineRow";
import { OfflineEntryRow } from "@/components/OfflineEntryRow";
import {
  SwipeableRow,
  type SwipeDeleteAccessibilityProps,
} from "@/components/SwipeableRow";
import { type OutboxSyncState } from "@/state/outbox";
import {
  formatWallClockTime,
  isOptimisticId,
  statusPresentation,
} from "@/state/today";
import { useTheme, spacing, typeScale, radius } from "@/theme";

import {
  isSyntheticSavedFoodItem,
  itemTimelineExtraRowTestID,
  itemTimelineRowTestID,
  mealDisplayName,
  pendingQuestionRowTestID,
  questionPlaceholderItem,
} from "./helpers";
import { MealEntryRow } from "./MealEntryRow";
import { type QuestionsByEvent } from "./usePartialClarifications";

/**
 * Wrap a deletable timeline row in the swipe-left-to-delete gesture (FTY-322),
 * or render it plain when deletion doesn't apply: the read-only past-day
 * timeline, a caller that passes no `onDeleteEvent`, or an optimistic
 * (not-yet-created) local entry — there is no server event to void until the
 * create acknowledges, and the submit machine already owns that entry's
 * rollback. Every server-backed row is wrapped; offline-queued captures never
 * reach this component (they return through `OfflineEntryRow` first). The
 * render-prop hands the child row the Delete custom-action props so the
 * destructive action stays reachable by VoiceOver on the row's own accessible
 * control, not just via the pointer-only swipe.
 */
function MaybeSwipeable({
  event,
  deleteLabel,
  onDeleteEvent,
  readOnly,
  children,
}: {
  event: LogEventDTO;
  deleteLabel: string;
  onDeleteEvent?: (event: LogEventDTO) => void;
  readOnly: boolean;
  children: (a11y: SwipeDeleteAccessibilityProps | undefined) => ReactNode;
}) {
  if (readOnly || !onDeleteEvent || isOptimisticId(event.id)) {
    return <>{children(undefined)}</>;
  }
  return (
    <SwipeableRow
      onDelete={() => onDeleteEvent(event)}
      deleteAccessibilityLabel={deleteLabel}
      deleteAnnouncement="Entry removed"
      testID={`swipe-row-${event.id}`}
    >
      {children}
    </SwipeableRow>
  );
}

/**
 * The rows of a partially-resolved entry (FTY-330): the mixed log's committed
 * `resolved` siblings as normal counted item rows, followed by one
 * pending-question row per still-open component (or, during a scoped
 * re-estimate, a single loading skeleton where the answered component resolves
 * in place).
 *
 * The committed siblings and the open component reuse the *existing* Today row
 * language: siblings are ordinary `ItemTimelineRow`s (provenance icon, kcal,
 * tap-to-correct), and each open question is an `ItemTimelineRow` in its
 * needs-a-detail treatment — muted, tagged, visibly uncounted — whose `name` is
 * the question `text` (which already names the component, e.g. "Which hummus was
 * that?"), never the raw diary phrase. Tapping a question row opens the clarify
 * sheet pre-targeted to that one question, so its answer resolves that exact
 * component and leaves the siblings untouched.
 */
function PartialEntryRows({
  event,
  items,
  questions,
  reestimating,
  onOpenItem,
  onOpenClarify,
  readOnly,
  a11y,
}: {
  event: LogEventDTO;
  items: readonly DerivedItem[];
  questions: readonly ClarificationQuestionDTO[];
  /** True while a just-answered component re-estimates (`processing`), FTY-349. */
  reestimating: boolean;
  onOpenItem?: (item: DerivedItem, logPhrase: string) => void;
  onOpenClarify?: (
    event: LogEventDTO,
    question?: ClarificationQuestionDTO,
  ) => void;
  readOnly: boolean;
  a11y: SwipeDeleteAccessibilityProps | undefined;
}) {
  return (
    <>
      {/* Committed siblings — counted, tappable, provenance unchanged. The first
          reuses the event-keyed test id so a pending skeleton resolves into it
          in place (FTY-180), never a swap between differently-keyed rows. */}
      {items.map((item, index) => {
        const key = index === 0 ? event.id : item.id;
        const testID =
          index === 0
            ? itemTimelineRowTestID(event.id)
            : itemTimelineExtraRowTestID(event.id, item.id);
        return (
          <ItemTimelineRow
            key={key}
            item={item}
            needsClarification={false}
            onPress={
              onOpenItem ? () => onOpenItem(item, event.raw_text) : undefined
            }
            readOnly={readOnly}
            testID={testID}
            {...a11y}
          />
        );
      })}

      {reestimating ? (
        // The answered component is being re-costed: its question row resolves
        // in place into a loading skeleton, while the siblings above stay put.
        <ItemTimelineRow
          loading
          accessibilityLabel={statusPresentation("processing").accessibilityLabel}
          testID={itemTimelineExtraRowTestID(event.id, "reestimate")}
          {...a11y}
        />
      ) : (
        // One pending-question row per still-open component.
        questions.map((question) => (
          <ItemTimelineRow
            key={question.id}
            item={questionPlaceholderItem(event, question)}
            needsClarification
            onPress={
              onOpenClarify ? () => onOpenClarify(event, question) : undefined
            }
            readOnly={readOnly}
            testID={pendingQuestionRowTestID(event.id, question.id)}
            {...a11y}
          />
        ))
      )}
    </>
  );
}

/**
 * One time-anchored cluster card of timeline rows (FTY-031). Each event renders
 * through the row that matches its status: an offline-queued capture, a resolved
 * item-forward row, an uncounted label proposal, a needs-a-detail row, an
 * actionable failed row, or the pending→resolve skeleton that fades in place.
 */
export function ClusterView({
  cluster,
  itemsByEvent,
  questionsByEvent = {},
  offlineStateById,
  resolveAnimIds,
  onOpenItem,
  onOpenProposal,
  onOpenClarify,
  onRetryFailed,
  onEditFailedAsText,
  onDeleteEvent,
  readOnly = false,
  colors,
}: {
  cluster: { anchorTime: string; events: readonly LogEventDTO[] };
  itemsByEvent: Readonly<Record<string, readonly DerivedItem[]>>;
  /** Open item-scoped clarification questions per partially-resolved event (FTY-330). */
  questionsByEvent?: QuestionsByEvent;
  offlineStateById: ReadonlyMap<string, OutboxSyncState>;
  resolveAnimIds: ReadonlySet<string>;
  onOpenItem?: (item: DerivedItem, logPhrase: string) => void;
  onOpenProposal?: (item: DerivedFoodItemDTO) => void;
  onOpenClarify?: (
    event: LogEventDTO,
    question?: ClarificationQuestionDTO,
  ) => void;
  onRetryFailed?: (event: LogEventDTO) => void;
  onEditFailedAsText?: (event: LogEventDTO) => void;
  /**
   * Soft-void a server-backed row via swipe-left-to-delete (FTY-322). Absent on
   * the read-only past-day timeline (historical days are view-only). Given, each
   * deletable row is wrapped so a left swipe reveals a destructive Delete and a
   * VoiceOver custom action deletes the owning event.
   */
  onDeleteEvent?: (event: LogEventDTO) => void;
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
          // resolved rows open correction. A multi-item meal collapses to one
          // expandable meal row (FTY-420); a single item is its own value row.
          if (event.status === "completed" && items.length > 0) {
            // Beat 1 — only genuine pending→resolved counted rows animate.
            const animateResolve = resolveAnimIds.has(event.id);
            const rowTestID = itemTimelineRowTestID(event.id);
            const firstItem = items[0];

            // FTY-420: a meal logged as one phrase groups under one log event
            // and renders as a single collapsed row — the event's
            // model-generated name (FTY-421/422) and the summed total — that
            // expands on tap into the per-item breakdown, each item editable
            // through the existing correction flow. It resolves in place from
            // the pending skeleton (same event-keyed testID, animate-fade).
            if (items.length > 1) {
              return (
                <MaybeSwipeable
                  key={event.id}
                  event={event}
                  deleteLabel={`Delete ${mealDisplayName(event)}`}
                  onDeleteEvent={onDeleteEvent}
                  readOnly={readOnly}
                >
                  {(a11y) => (
                    <MealEntryRow
                      event={event}
                      items={items}
                      animateResolve={animateResolve}
                      onOpenItem={onOpenItem}
                      onOpenProposal={onOpenProposal}
                      readOnly={readOnly}
                      testID={rowTestID}
                      {...a11y}
                    />
                  )}
                </MaybeSwipeable>
              );
            }

            // Single resolved/proposed item: the item-forward value row.
            const deleteLabel = firstItem
              ? `Delete ${firstItem.name}`
              : "Delete entry";
            return (
              <MaybeSwipeable
                key={event.id}
                event={event}
                deleteLabel={deleteLabel}
                onDeleteEvent={onDeleteEvent}
                readOnly={readOnly}
              >
                {(a11y) => {
                  if (!firstItem) return null;
                  return firstItem.item_type === "food" &&
                    firstItem.status === "proposed" ? (
                    <ItemTimelineRow
                      item={firstItem}
                      proposal
                      onPress={
                        onOpenProposal ? () => onOpenProposal(firstItem) : undefined
                      }
                      readOnly={readOnly}
                      testID={rowTestID}
                      {...a11y}
                    />
                  ) : (
                    <ItemTimelineRow
                      item={firstItem}
                      needsClarification={false}
                      onPress={
                        onOpenItem
                          ? () => onOpenItem(firstItem, event.raw_text)
                          : undefined
                      }
                      readOnly={readOnly}
                      animateResolve={animateResolve}
                      testID={rowTestID}
                      {...a11y}
                    />
                  );
                }}
              </MaybeSwipeable>
            );
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
            const firstSynthetic = syntheticItems[0];
            return (
              <MaybeSwipeable
                key={event.id}
                event={event}
                deleteLabel={
                  firstSynthetic ? `Delete ${firstSynthetic.name}` : "Delete entry"
                }
                onDeleteEvent={onDeleteEvent}
                readOnly={readOnly}
              >
                {(a11y) =>
                  syntheticItems.map((item) => (
                    <ItemTimelineRow
                      key={item.id}
                      item={item}
                      needsClarification={false}
                      onPress={
                        onOpenItem ? () => onOpenItem(item, event.raw_text) : undefined
                      }
                      readOnly={readOnly}
                      testID={itemTimelineExtraRowTestID(event.id, item.id)}
                      {...a11y}
                    />
                  ))
                }
              </MaybeSwipeable>
            );
          }

          // partially_resolved (FTY-278/330): a mixed log whose costable
          // siblings are committed and counted, with one open item-scoped
          // question per still-unresolved component. Render the committed
          // siblings as normal counted rows plus one pending-question row per
          // open component. A scoped re-estimate (the event momentarily flips
          // `partially_resolved → processing` after the user answers, per
          // FTY-349) keeps the same committed siblings on the by-date feed, so
          // it renders here too — the answered component's row becomes a loading
          // skeleton in place while the siblings stay put (calm, no dip).
          const questions = questionsByEvent[event.id] ?? [];
          const isScopedReestimate =
            event.status === "processing" && items.length > 0;
          if (event.status === "partially_resolved" || isScopedReestimate) {
            const firstItem = items[0];
            const deleteLabel = firstItem
              ? `Delete ${firstItem.name}`
              : "Delete entry";
            return (
              <MaybeSwipeable
                key={event.id}
                event={event}
                deleteLabel={deleteLabel}
                onDeleteEvent={onDeleteEvent}
                readOnly={readOnly}
              >
                {(a11y) => (
                  <PartialEntryRows
                    event={event}
                    items={items}
                    questions={questions}
                    reestimating={isScopedReestimate}
                    onOpenItem={onOpenItem}
                    onOpenClarify={onOpenClarify}
                    readOnly={readOnly}
                    a11y={a11y}
                  />
                )}
              </MaybeSwipeable>
            );
          }

          // needs_clarification → legible, inviting "needs a detail" row whose
          // tap opens the clarify-mode sheet (FTY-149).
          if (event.status === "needs_clarification") {
            return (
              <MaybeSwipeable
                key={event.id}
                event={event}
                deleteLabel="Delete entry"
                onDeleteEvent={onDeleteEvent}
                readOnly={readOnly}
              >
                {(a11y) => (
                  <EntryRow
                    event={event}
                    onPress={onOpenClarify ? () => onOpenClarify(event) : undefined}
                    readOnly={readOnly}
                    {...a11y}
                  />
                )}
              </MaybeSwipeable>
            );
          }

          // failed → calm, actionable "couldn't read that" row with Retry +
          // Edit as text; never a static dead-end (FTY-176).
          if (event.status === "failed") {
            return (
              <MaybeSwipeable
                key={event.id}
                event={event}
                deleteLabel="Delete entry"
                onDeleteEvent={onDeleteEvent}
                readOnly={readOnly}
              >
                {(a11y) => (
                  <EntryRow
                    event={event}
                    onRetry={onRetryFailed ? () => onRetryFailed(event) : undefined}
                    onEditAsText={
                      onEditFailedAsText
                        ? () => onEditFailedAsText(event)
                        : undefined
                    }
                    readOnly={readOnly}
                    {...a11y}
                  />
                )}
              </MaybeSwipeable>
            );
          }

          // pending / processing with no resolved item yet → the "thinking"
          // state: a Skeleton shimmer sized to the resolved ItemTimelineRow it
          // will become (FTY-180), so the row resolves in place with no
          // layout shift. Never the literal "Waiting"/"Estimating" text. A
          // server-backed row is deletable even mid-estimate (FTY-322): only
          // pending *offline* and optimistic rows are excluded, and those never
          // reach this branch wrapped (see MaybeSwipeable).
          if (event.status === "pending" || event.status === "processing") {
            return (
              <MaybeSwipeable
                key={event.id}
                event={event}
                deleteLabel="Delete entry"
                onDeleteEvent={onDeleteEvent}
                readOnly={readOnly}
              >
                {(a11y) => (
                  <ItemTimelineRow
                    loading
                    accessibilityLabel={
                      statusPresentation(event.status).accessibilityLabel
                    }
                    testID={itemTimelineRowTestID(event.id)}
                    {...a11y}
                  />
                )}
              </MaybeSwipeable>
            );
          }

          // Freshly completed and still waiting on by-date items: hold the same
          // loading row. Items fade in; confirmed no-items falls through below.
          if (resolveAnimIds.has(event.id)) {
            return (
              <MaybeSwipeable
                key={event.id}
                event={event}
                deleteLabel="Delete entry"
                onDeleteEvent={onDeleteEvent}
                readOnly={readOnly}
              >
                {(a11y) => (
                  <ItemTimelineRow
                    loading
                    accessibilityLabel={
                      statusPresentation("processing").accessibilityLabel
                    }
                    testID={itemTimelineRowTestID(event.id)}
                    {...a11y}
                  />
                )}
              </MaybeSwipeable>
            );
          }

          // completed with no items and no in-flight resolve — an entry already
          // completed on initial load, or the rare estimate that produced nothing
          // to show → terminal status placeholder, not a permanent shimmer. Still
          // a server-backed row the user may want gone, so it keeps the swipe
          // Delete and its VoiceOver custom action (FTY-322).
          return (
            <MaybeSwipeable
              key={event.id}
              event={event}
              deleteLabel="Delete entry"
              onDeleteEvent={onDeleteEvent}
              readOnly={readOnly}
            >
              {(a11y) => <EntryRow event={event} readOnly={readOnly} {...a11y} />}
            </MaybeSwipeable>
          );
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
