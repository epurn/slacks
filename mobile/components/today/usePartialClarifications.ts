import { useEffect, useMemo, useRef, useState } from "react";

import {
  getLogEventClarification as getLogEventClarificationApi,
  type ClarificationQuestionDTO,
  type LogEventDTO,
} from "@/api/logEvents";
import { type ApiSession } from "@/state/session";

/** Open item-scoped clarification questions keyed by their `partially_resolved` event id. */
export type QuestionsByEvent = Readonly<
  Record<string, readonly ClarificationQuestionDTO[]>
>;

/** Shared stable empty view so a no-partial-events day never re-renders consumers. */
const EMPTY: QuestionsByEvent = Object.freeze({});

/**
 * Backoff before re-reading a partial event's question after a *failed* read that
 * left the open component with nothing to show. A `partially_resolved` event is
 * not poll-worthy (`state/polling.ts`), so the timeline's normal poll never
 * retries this read — without a self-scheduled retry a transient first-read
 * failure would hide the open component (and its answer CTA) until a manual
 * refresh. The retry runs only while a question is genuinely missing and stops
 * the moment one is fetched (or the event leaves `partially_resolved`), so a
 * settled partial day schedules no timer.
 */
export const PARTIAL_CLARIFICATION_RETRY_MS = 4000;

/**
 * Fetch the open item-scoped clarification questions for the timeline's
 * `partially_resolved` events (FTY-330).
 *
 * A partial event's committed `resolved` siblings arrive on the item-forward
 * by-date feed (FTY-198) like any counted row, but its open question is not in
 * that feed — it is discoverable only through the status-gated clarification
 * read (`clarification.md`). So the timeline renders one pending-question row
 * per open component from the question `text` this hook fetches.
 *
 * The read is keyed on the *set* of partial event ids, not the poll tick: a
 * question's `text` is stable while its event stays `partially_resolved`, and a
 * fresh round always passes through `processing` first (dropping the id from the
 * set, then re-adding it), so keying on the set alone re-fetches exactly when a
 * new round can have replaced the questions — no per-poll refetch churn. A
 * failed read keeps the last-known questions so the row never flickers away
 * (calm by default); a failed read that had *nothing* to keep (the open
 * component would otherwise vanish) schedules a backoff retry, because a partial
 * event is not poll-worthy and would otherwise stay hidden until a manual
 * refresh; an event that leaves `partially_resolved` drops out because the next
 * result set no longer includes it.
 */
export function usePartialClarifications({
  apiSession,
  events,
  getClarification,
  reloadKey,
}: {
  apiSession: ApiSession | null;
  events: readonly LogEventDTO[];
  getClarification: typeof getLogEventClarificationApi;
  /** Bumped on manual refresh so a pull re-reads the open questions too. */
  reloadKey: number;
}): QuestionsByEvent {
  // Raw fetched questions keyed by event id. A successful read replaces an id's
  // entry; a failed read keeps its prior entry (no flicker). Entries are pruned
  // to the current partial set at read time and again in the returned view.
  const [fetched, setFetched] = useState<QuestionsByEvent>(EMPTY);
  // Mirror of `fetched` so the async read can merge against the latest value
  // without threading it through a functional update (the retry decision below
  // needs to know which ids ended up with no question).
  const fetchedRef = useRef<QuestionsByEvent>(fetched);
  // Bumped by the retry timer to re-run the effect when a failed read left an
  // open component with no question to show.
  const [retryTick, setRetryTick] = useState(0);

  const partialIds = useMemo(
    () =>
      events
        .filter((event) => event.status === "partially_resolved")
        .map((event) => event.id)
        .sort(),
    [events],
  );
  // A stable primitive dep so the effect re-runs only when the *membership* of
  // the partial set changes, not on every new `events` array a poll produces.
  const partialKey = partialIds.join(",");

  useEffect(() => {
    // Scope the failed-read fallback to one *continuous* partial round: drop any
    // cached questions for events no longer in the partial set. A partial event
    // that leaves `partially_resolved` (answered → processing) and later
    // re-enters opens a fresh clarification round whose questions replace the old
    // ones (`clarification.md`). Without this prune the departed id's questions
    // linger in `fetchedRef`, so a transient failed read on re-entry would fall
    // back to the stale (already-answered) question — re-showing it, hiding the
    // real open component, and sending the wrong question id to the answer API.
    // Pruning here runs synchronously on every membership change, including when
    // the set empties (the early return below still lets this run first), so the
    // status gap is always cleared before an id can return.
    const partialSet = new Set(partialIds);
    const prevFetched = fetchedRef.current;
    const hasStale = Object.keys(prevFetched).some((id) => !partialSet.has(id));
    if (hasStale) {
      const pruned: Record<string, readonly ClarificationQuestionDTO[]> = {};
      for (const id of partialIds) {
        if (prevFetched[id]) pruned[id] = prevFetched[id];
      }
      fetchedRef.current = pruned;
      setFetched(pruned);
    }

    if (!apiSession || partialIds.length === 0) return;
    let active = true;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;
    Promise.all(
      partialIds.map((id) =>
        getClarification(apiSession, id).then(
          (result) => [id, result.questions] as const,
          // A transient read failure: keep whatever this id already showed.
          () => [id, null] as const,
        ),
      ),
    ).then((results) => {
      if (!active) return;
      const prev = fetchedRef.current;
      const next: Record<string, readonly ClarificationQuestionDTO[]> = {};
      for (const [id, questions] of results) {
        if (questions !== null) {
          next[id] = questions;
        } else if (prev[id]) {
          next[id] = prev[id];
        }
      }
      fetchedRef.current = next;
      setFetched(next);
      // A partial event whose read failed with nothing shown before has no
      // question row yet — retry on a timer so a transient first-read failure
      // can't hide the open component until a manual refresh. Self-terminating:
      // once every open component has a question (or the partial set empties)
      // no id is missing, so no further timer is scheduled.
      const anyMissing = partialIds.some((id) => next[id] === undefined);
      if (anyMissing) {
        retryTimer = setTimeout(() => {
          if (active) setRetryTick((tick) => tick + 1);
        }, PARTIAL_CLARIFICATION_RETRY_MS);
      }
    });
    return () => {
      active = false;
      if (retryTimer !== undefined) clearTimeout(retryTimer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiSession, getClarification, partialKey, reloadKey, retryTick]);

  // Return only questions for events that are *currently* partially-resolved, so
  // an event that has advanced (answered → processing) drops its stale question
  // rows immediately without a setState-in-effect. No partial events → the
  // shared empty view (stable identity, no consumer re-render).
  return useMemo(() => {
    if (partialIds.length === 0) return EMPTY;
    const view: Record<string, readonly ClarificationQuestionDTO[]> = {};
    let any = false;
    for (const id of partialIds) {
      if (fetched[id]) {
        view[id] = fetched[id];
        any = true;
      }
    }
    return any ? view : EMPTY;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fetched, partialKey]);
}
