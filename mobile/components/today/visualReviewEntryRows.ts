/**
 * Today failed / needs-clarification EntryRow visual-review presets (FTY-342).
 *
 * These rows are inline Today timeline states, not modal sub-states. The seam is
 * therefore just a Today-owned synthetic day fixture registered through the
 * FTY-247 visual-review API: activating a preset seeds the event-list and
 * item-forward reads so ClusterView renders the real EntryRow branch on initial
 * load, with no live backend and no scripted taps.
 *
 * Registration is inert on its own. The presets become reachable only through
 * the `isE2EMode()`-gated visual-review deep-link route and the E2E mock fetch.
 */

import type { DailySummaryDTO } from "@/api/dailySummary";
import {
  registerVisualReviewPreset,
  type VisualReviewFetchContext,
} from "@/e2e/visualReview";
import {
  E2E_CLARIFY_EVENT,
  E2E_DAILY_SUMMARY,
  E2E_FAILED_EVENT,
} from "@/e2e/fixtures";

export const TODAY_FAILED_PRESET_NAME = "today.failed";
export const TODAY_NEEDS_CLARIFICATION_PRESET_NAME =
  "today.needs_clarification";

const EMPTY_LIST: unknown[] = [];

/**
 * Summary for the clarify preset: an event-level needs_clarification event
 * contributes one uncounted unit (`daily-summary.md` → uncounted_entries).
 * The failed preset serves the plain zero summary instead — the contract
 * explicitly excludes `failed` events from `uncounted_entries` (a distinct
 * retry state), so `uncounted_entries: 1` is a shape the backend can never
 * produce for a failed-only day.
 */
const CLARIFY_UNCOUNTED_SUMMARY: DailySummaryDTO = {
  ...E2E_DAILY_SUMMARY,
  uncounted_entries: 1,
};

function get(suffix: string): (ctx: VisualReviewFetchContext) => boolean {
  return (ctx) => ctx.method === "GET" && ctx.pathEnd.endsWith(suffix);
}

registerVisualReviewPreset({
  name: TODAY_FAILED_PRESET_NAME,
  route: "/",
  settledPath: "/",
  responses: [
    {
      match: get("/log-events/by-date"),
      body: [{ event: E2E_FAILED_EVENT, items: EMPTY_LIST }],
    },
    { match: get("/log-events"), body: [E2E_FAILED_EVENT] },
    { match: get("/daily-summary"), body: E2E_DAILY_SUMMARY },
  ],
});

registerVisualReviewPreset({
  name: TODAY_NEEDS_CLARIFICATION_PRESET_NAME,
  route: "/",
  settledPath: "/",
  responses: [
    {
      match: get("/log-events/by-date"),
      body: [{ event: E2E_CLARIFY_EVENT, items: EMPTY_LIST }],
    },
    { match: get("/log-events"), body: [E2E_CLARIFY_EVENT] },
    { match: get("/daily-summary"), body: CLARIFY_UNCOUNTED_SUMMARY },
  ],
});
