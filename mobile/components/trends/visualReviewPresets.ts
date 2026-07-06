/**
 * Trends-owned visual-review sub-state preset (FTY-264).
 *
 * Registers `trends.adherence_retry` through FTY-247's registration API
 * (`registerVisualReviewPreset`) — the join contract the per-screen seam
 * stories (FTY-262..268) use to contribute a sub-state preset without editing
 * the shared registry (`e2e/visualReview/registry.ts`) or the in-scope manifest
 * (`e2e/visualReview/presets.ts`).
 *
 * The adherence-strip retry state needs no screen-owned behaviour seam:
 * TrendsScreen already renders the adherence card's error/retry UI whenever the
 * `/daily-summary/range` read rejects (its `adherencePhase === "error"` branch),
 * so a mock-fetch error fixture for that one endpoint reaches the state
 * deterministically. The weight card's `/weight-entries` read is left on the
 * default populated fixture, so only the adherence card renders its retry state.
 *
 * Registering a preset here has no effect outside an active visual-review
 * session: `registerVisualReviewPreset` only writes to an in-memory map, and
 * that map is read only by the `isE2EMode()`-gated deep-link route
 * (`app/__visual-review.tsx`) — the same shape the shipped `presets.ts`
 * manifest already uses, registered unconditionally at import time. Imported
 * once, for this registration side effect, from `TrendsScreen.tsx` so it runs
 * at app boot (before the visual-review route can look the name up) without
 * editing any shared visual-review file.
 */

import {
  registerVisualReviewPreset,
  type VisualReviewFetchContext,
} from "@/e2e/visualReview";

function isDailySummaryRangeRead(ctx: VisualReviewFetchContext): boolean {
  return ctx.method === "GET" && ctx.pathEnd.endsWith("/daily-summary/range");
}

registerVisualReviewPreset({
  name: "trends.adherence_retry",
  route: "/trends",
  settledPath: "/trends",
  responses: [
    {
      match: isDailySummaryRangeRead,
      body: {
        detail: "synthetic range-read failure (FTY-264 visual-review fixture)",
      },
      status: 500,
    },
  ],
});
