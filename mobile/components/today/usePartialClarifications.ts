import { useEffect, useMemo, useState } from "react";

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
 * (calm by default); an event that leaves `partially_resolved` drops out because
 * the next result set no longer includes it.
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
    if (!apiSession || partialIds.length === 0) return;
    let active = true;
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
      setFetched((prev) => {
        const next: Record<string, readonly ClarificationQuestionDTO[]> = {};
        for (const [id, questions] of results) {
          if (questions !== null) {
            next[id] = questions;
          } else if (prev[id]) {
            next[id] = prev[id];
          }
        }
        return next;
      });
    });
    return () => {
      active = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [apiSession, getClarification, partialKey, reloadKey]);

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
