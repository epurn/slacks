import { useEffect, useMemo, useRef, useState } from "react";

import { type DerivedItem } from "@/api/derivedItems";
import { type LogEventDTO } from "@/api/logEvents";
import { reducedMotionDuration } from "@/theme";
import { entryResolvedHaptic } from "@/theme/haptics";

import { hasOwn, type Phase } from "./helpers";

/**
 * Beat 1 — entry resolve (FTY-181). Detects pending→`completed` (counted)
 * transitions so a resolve fires the soft-tap haptic once per resolved event and
 * eases the resolved value's row in.
 *
 * `seenCompleted` is `null` until the first events load seeds it, so an
 * already-completed entry present on initial load never beats on mount. The
 * detection runs in render (the "adjust state on prop change" pattern), and a
 * `resolveBeatCount` — advanced by the number of freshly-resolved events each
 * reconciliation — hands the actual haptics to an effect (a side effect must not
 * run during render). The effect fires the delta since it last ran, so a poll
 * batch where several entries complete at once beats once per event, not one tap
 * total (FTY-181 review).
 *
 * Returns the ids whose value row should ease in (`resolveAnimIds`) and whether a
 * fresh completion is still waiting on the item-forward feed
 * (`hasFreshResolveAwaitingItems`), which keeps the timeline polling until the
 * skeleton can resolve in place.
 */
export function useEntryResolveBeats(
  events: readonly LogEventDTO[],
  phase: Phase,
  itemsByEvent: Readonly<Record<string, readonly DerivedItem[]>>,
): { resolveAnimIds: ReadonlySet<string>; hasFreshResolveAwaitingItems: boolean } {
  const [seenCompleted, setSeenCompleted] = useState<ReadonlySet<string> | null>(
    null,
  );
  const [resolveAnimIds, setResolveAnimIds] = useState<ReadonlySet<string>>(
    () => new Set(),
  );
  const [resolveBeatCount, setResolveBeatCount] = useState(0);
  const firedResolveBeats = useRef(0);

  // Detection (render phase). Compute the set of completed event ids and, once
  // seeded, diff it against the last-seen set: any newly-completed id is a
  // pending→resolved transition. Detection only starts once the first load has
  // landed (`phase === "ready"`); the seed then captures the initially-loaded
  // completed entries, so an entry already completed on load is never treated as
  // a fresh resolve — no beat on mount.
  const completedIds = useMemo(() => {
    const ids = new Set<string>();
    for (const event of events) {
      if (event.status === "completed") ids.add(event.id);
    }
    return ids;
  }, [events]);
  if (phase === "ready") {
    if (seenCompleted === null) {
      setSeenCompleted(completedIds);
    } else {
      const fresh: string[] = [];
      for (const id of completedIds) {
        if (!seenCompleted.has(id)) fresh.push(id);
      }
      if (fresh.length > 0) {
        setSeenCompleted(completedIds);
        setResolveAnimIds((prev) => {
          const next = new Set(prev);
          for (const id of fresh) next.add(id);
          return next;
        });
        setResolveBeatCount((n) => n + fresh.length);
      }
    }
  }

  // Fire one entry-resolve haptic per newly-resolved event.
  useEffect(() => {
    const unfired = resolveBeatCount - firedResolveBeats.current;
    if (unfired <= 0) return;
    firedResolveBeats.current = resolveBeatCount;
    for (let i = 0; i < unfired; i++) entryResolvedHaptic();
  }, [resolveBeatCount]);

  useEffect(() => {
    if (resolveAnimIds.size === 0) return;
    const timeout = setTimeout(() => {
      setResolveAnimIds((prev) => {
        let next: Set<string> | null = null;
        for (const id of prev) {
          if (hasOwn(itemsByEvent, id)) {
            next ??= new Set(prev);
            next.delete(id);
          }
        }
        return next ?? prev;
      });
    }, reducedMotionDuration);
    return () => clearTimeout(timeout);
  }, [itemsByEvent, resolveAnimIds]);

  const hasFreshResolveAwaitingItems = useMemo(() => {
    for (const id of resolveAnimIds) {
      if (!hasOwn(itemsByEvent, id)) return true;
    }
    return false;
  }, [itemsByEvent, resolveAnimIds]);

  return { resolveAnimIds, hasFreshResolveAwaitingItems };
}
