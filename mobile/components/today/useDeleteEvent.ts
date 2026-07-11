import { useCallback, useMemo, useRef, useState } from "react";
import type { Dispatch, SetStateAction } from "react";

import type { ApiSession } from "@/api/client";
import {
  getDailySummary as getDailySummaryApi,
  type DailySummaryDTO,
} from "@/api/dailySummary";
import { type DerivedItem } from "@/api/derivedItems";
import {
  deleteLogEvent as deleteLogEventApi,
  listTodayLogEventEntries as listTodayLogEventEntriesApi,
  type LogEventDTO,
} from "@/api/logEvents";

import {
  mergeServerItems,
  messageFor,
  summaryMinusDeletedEvent,
} from "./helpers";

/**
 * Owns Today's delete (soft-void) flow (FTY-322), composed into `useTodayData`
 * like the other focused sub-hooks. A delete hides the row and recomputes the
 * hero/day totals in the same beat, round-trips the void to the FTY-321
 * endpoint, reconciles with server truth on success, and restores the row and
 * totals with a calm inline error on failure — never a crash, never a silent
 * loss, and never totals that still count a row that is gone.
 */
export function useDeleteEvent({
  apiSession,
  deleteEvent,
  loadEntries,
  getDailySummary,
  itemsByEvent,
  summary,
  setEvents,
  setItemsByEvent,
  setSummary,
  setSummaryError,
}: {
  apiSession: ApiSession | null;
  deleteEvent: typeof deleteLogEventApi;
  loadEntries: typeof listTodayLogEventEntriesApi;
  getDailySummary: typeof getDailySummaryApi;
  itemsByEvent: Readonly<Record<string, readonly DerivedItem[]>>;
  /** The last server-fetched summary; `displaySummary` derives from it. */
  summary: DailySummaryDTO | null;
  setEvents: Dispatch<SetStateAction<readonly LogEventDTO[]>>;
  setItemsByEvent: Dispatch<
    SetStateAction<Readonly<Record<string, readonly DerivedItem[]>>>
  >;
  setSummary: Dispatch<SetStateAction<DailySummaryDTO | null>>;
  setSummaryError: Dispatch<SetStateAction<string | null>>;
}) {
  // Soft-voided (deleted) server events. Adding an id hides the row
  // immediately (optimistic removal) via `displayEvents`, and — because that
  // filter is applied on every render regardless of what a poll writes back
  // into `events` — it also guards the poll-resurrect race: an in-flight
  // list/poll that still carries a just-deleted event can never flash the row
  // back. A failed delete removes the id again, restoring the row. Once the
  // server confirms the void the event is excluded from every read, so keeping
  // its (unique UUID) id here indefinitely is harmless. Mirrors the
  // `supersededFailedIds` in-place-hide pattern in `useTodayData`.
  const [deletedEventIds, setDeletedEventIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const [deleteError, setDeleteError] = useState<string | null>(null);
  // Optimistic totals adjustments — the totals analog of the `deletedEventIds`
  // render-time filter above. Adding an entry subtracts the deleted event's
  // finalized contribution from every summary the hook returns (see
  // `displaySummary`), so the hero/day totals recompute the same beat the row
  // is hidden — never only after the DELETE round-trip and summary refetch,
  // and immune to a racing summary read that still counts the row. An entry is
  // removed when the delete fails (restoring the totals with the row) or when
  // a summary response that reflects the void lands (`beginSummaryRead`), at
  // which point the server figure takes over seamlessly.
  const [summaryAdjustments, setSummaryAdjustments] = useState<
    ReadonlyMap<
      string,
      { deletedEvent: LogEventDTO; items: readonly DerivedItem[] }
    >
  >(() => new Map());
  // Event ids whose DELETE the server has confirmed. A summary request issued
  // AFTER confirmation reflects the void, so its response clears those ids'
  // adjustments; a request issued earlier (the initial load or a poll racing
  // the DELETE) may still count the row, so its response keeps them and stays
  // adjusted. A ref, not state: read/written only in fetch callbacks and event
  // handlers, never during render.
  const confirmedDeleteIds = useRef(new Set<string>());

  // Start a daily-summary read: call this when the request is ISSUED, then land
  // the response through the returned callback. It stores the server figure and
  // retires the adjustments this response already accounts for — the deletes
  // that were confirmed before the request went out.
  const beginSummaryRead = useCallback(() => {
    const confirmedAtIssue = [...confirmedDeleteIds.current];
    return (loaded: DailySummaryDTO) => {
      setSummary(loaded);
      setSummaryAdjustments((prev) => {
        if (!confirmedAtIssue.some((id) => prev.has(id))) return prev;
        const next = new Map(prev);
        for (const id of confirmedAtIssue) next.delete(id);
        return next;
      });
    };
  }, [setSummary]);

  const handleDeleteEvent = useCallback(
    async (target: LogEventDTO) => {
      if (!apiSession) return;
      setDeleteError(null);
      setDeletedEventIds((prev) => new Set(prev).add(target.id));
      // Snapshot the items now: the success path (and a reconciling poll) drops
      // them from `itemsByEvent`, but the adjustment must keep subtracting this
      // event's contribution until a post-void summary lands.
      const items = itemsByEvent[target.id] ?? [];
      setSummaryAdjustments((prev) =>
        new Map(prev).set(target.id, { deletedEvent: target, items }),
      );
      try {
        await deleteEvent(apiSession, target.id);
        confirmedDeleteIds.current.add(target.id);
        setEvents((prev) => prev.filter((event) => event.id !== target.id));
        setItemsByEvent((prev) => {
          if (!(target.id in prev)) return prev;
          const { [target.id]: _removed, ...rest } = prev;
          return rest;
        });
        // Refresh the day feed and totals in place so the removal is reflected
        // everywhere the entry counted (server is the source of truth post-void).
        loadEntries(apiSession).then(
          (entries) =>
            setItemsByEvent((prev) => mergeServerItems(prev, entries)),
          () => {
            // Keep the current items; the next poll retries.
          },
        );
        const landSummary = beginSummaryRead();
        getDailySummary(apiSession).then(
          (loaded) => {
            landSummary(loaded);
            setSummaryError(null);
          },
          () => {
            // Keep the adjusted totals — already correct for the removal — and
            // let the next successful summary read reconcile and retire them.
          },
        );
      } catch (error) {
        setDeletedEventIds((prev) => {
          const next = new Set(prev);
          next.delete(target.id);
          return next;
        });
        // Drop the adjustment with the restore: the void never happened, so the
        // base summary still (correctly) counts the row.
        setSummaryAdjustments((prev) => {
          if (!prev.has(target.id)) return prev;
          const next = new Map(prev);
          next.delete(target.id);
          return next;
        });
        setDeleteError(messageFor(error, "delete"));
      }
    },
    [
      apiSession,
      deleteEvent,
      loadEntries,
      getDailySummary,
      itemsByEvent,
      beginSummaryRead,
      setEvents,
      setItemsByEvent,
      setSummaryError,
    ],
  );

  // The summary the screen renders: the last server figure minus every active
  // delete adjustment, applied on every render — so no matter which read last
  // wrote `summary` (initial load, a poll that raced the void, or the
  // post-void refetch), the hero/day totals never count an optimistically
  // deleted row. Mirrors the `displayEvents` filter for the totals.
  const displaySummary = useMemo(() => {
    if (!summary || summaryAdjustments.size === 0) return summary;
    let adjusted = summary;
    for (const { deletedEvent, items } of summaryAdjustments.values()) {
      adjusted = summaryMinusDeletedEvent(adjusted, deletedEvent, items);
    }
    return adjusted;
  }, [summary, summaryAdjustments]);

  return {
    deletedEventIds,
    deleteError,
    displaySummary,
    beginSummaryRead,
    handleDeleteEvent,
  };
}
