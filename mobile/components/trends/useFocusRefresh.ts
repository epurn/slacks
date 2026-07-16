/**
 * Focus-gain refresh signal for the Trends screen (FTY-365).
 *
 * The Trends tab stays mounted across tab switches, so data loaded at first
 * mount would otherwise be served stale forever — deleting an item on Today
 * (FTY-322 void-delete), logging a new one, or even a day rollover never
 * appeared until an app restart. This hook turns the screen's
 * foreground+focus signal (`useScreenActive`, the same idiom Today's
 * quick-add chips use for their focus-edge fetch, FTY-341) into the two
 * refresh inputs the screen's read effects key on:
 *
 * - `focusNow`: the clock, re-read at each focus gain — the date window
 *   derives from the time of focus, not first mount, so it rolls across
 *   midnight while the app stays open.
 * - `focusSeq`: a counter bumped exactly once per focus gain — a fresh
 *   dependency value for the read effects, so each focus gain triggers one
 *   refetch and nothing else does.
 *
 * The initial mount is deliberately NOT a focus edge (`wasActive` starts
 * true): the screen's read effects already fetch on mount, and bumping the
 * sequence there would issue a duplicate first read. Edge detection lives in
 * a ref rather than effect deps, so re-renders while the screen stays
 * focused never bump the sequence — refresh cadence is focus-driven only,
 * never a timer and never a render loop.
 */

import { useEffect, useRef, useState } from "react";

export function useFocusRefresh(
  isActive: boolean,
  now: () => Date,
): { focusNow: Date; focusSeq: number } {
  const [state, setState] = useState(() => ({ focusNow: now(), focusSeq: 0 }));
  // Mount counts as already-active: only a genuine blur → focus transition
  // is a refresh edge (see module doc).
  const wasActive = useRef(true);
  useEffect(() => {
    if (!isActive) {
      wasActive.current = false;
      return;
    }
    if (wasActive.current) return;
    wasActive.current = true;
    setState((prev) => ({ focusNow: now(), focusSeq: prev.focusSeq + 1 }));
  }, [isActive, now]);
  return state;
}
