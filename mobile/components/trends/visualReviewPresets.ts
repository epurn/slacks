/**
 * Trends-owned visual-review sub-state presets (FTY-264, FTY-431).
 *
 * Registers `trends.adherence_retry` (the range-read failure state) and
 * `trends.adherence_mix` (a range whose newest days cover all four
 * adherence-cell states, for the FTY-431 off-target restyle evidence) through
 * FTY-247's registration API
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
 * The mixed-adherence state needs no seam either — it is purely the range
 * fixture the card already renders from.
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

import type { DailySummaryDTO } from "@/api/dailySummary";
import { E2E_TARGET, e2eDayRange } from "@/e2e/fixtures";
import {
  registerVisualReviewPreset,
  type VisualReviewFetchContext,
} from "@/e2e/visualReview";
import type { AdherenceDayState } from "@/state/trends";

function isDailySummaryRangeRead(ctx: VisualReviewFetchContext): boolean {
  return ctx.method === "GET" && ctx.pathEnd.endsWith("/daily-summary/range");
}

/** Read a query-string parameter off a full request URL (the range read's from/to window). */
function queryParam(url: string, key: string): string | null {
  const q = url.split("?")[1];
  if (!q) return null;
  for (const pair of q.split("&")) {
    const [k, v] = pair.split("=");
    if (k === key) return decodeURIComponent(v ?? "");
  }
  return null;
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

// ─── trends.adherence_mix (FTY-431) ───────────────────────────────────────────
//
// A range fixture whose most recent days carry all four adherence-cell states,
// so one screenshot of the strip shows on-target, off-target, no-target, and
// no-data side by side — the evidence the off-target restyle needs in both
// schemes. The default mock's range (`e2eDailySummaryRange`) never produces a
// `no-target` day (its unlogged days carry no target at all, which reads as
// `no-data`), so it cannot show the full set.
//
// Same seam as `trends.adherence_retry` above: a fixture for one endpoint, no
// Trends-code behaviour seam, registered from the Trends lane.

/**
 * States for the most recent days, newest first (offset 0 = today). The strip
 * auto-scrolls to its newest end, so this prefix is exactly what a screenshot
 * frames; all four states appear inside the first ~8 cells, which is what fits
 * an iPhone-width viewport. Days older than this list are unlogged history.
 */
const MIX_RECENT_STATES: readonly AdherenceDayState[] = [
  "on-target",
  "off-target",
  "on-target",
  "no-target",
  "off-target",
  "on-target",
  "no-data",
  "off-target",
  "on-target",
  "on-target",
  "off-target",
  "no-target",
  "on-target",
  "off-target",
];

/** Synthetic intake for a state, against the 2,000 kcal `E2E_TARGET`. */
function mixDaySummary(date: string, state: AdherenceDayState): DailySummaryDTO {
  const unlogged = {
    date,
    intake: { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 },
    has_intake: false,
    uncounted_entries: 0,
    target: null,
    exercise: { active_calories: 0 },
  } satisfies DailySummaryDTO;
  if (state === "no-data") return unlogged;

  // On-target sits inside the ±10% band; off-target alternates a miss under and
  // a miss over, so the strip's coral cells are not all "ate too little".
  const calories = state === "on-target" ? 1980 : state === "no-target" ? 1740 : 1500;
  return {
    date,
    intake: {
      calories,
      protein_g: Math.round(calories * 0.075),
      carbs_g: Math.round(calories * 0.1),
      fat_g: Math.round(calories * 0.0325),
    },
    has_intake: true,
    uncounted_entries: 0,
    // A `no-target` day is logged but had no target set that day.
    target: state === "no-target" ? null : E2E_TARGET,
    exercise: { active_calories: 0 },
  };
}

/** Build the mixed range for the window the client asked for (oldest first). */
function adherenceMixRange(from: string, to: string): DailySummaryDTO[] {
  const days = e2eDayRange(from, to);
  return days.map((date, i) => {
    const offsetFromNewest = days.length - 1 - i;
    const state = MIX_RECENT_STATES[offsetFromNewest] ?? "no-data";
    return mixDaySummary(date, state);
  });
}

registerVisualReviewPreset({
  name: "trends.adherence_mix",
  route: "/trends",
  settledPath: "/trends",
  responses: [
    {
      match: isDailySummaryRangeRead,
      body: (ctx: VisualReviewFetchContext) => {
        const from = queryParam(ctx.url, "from");
        const to = queryParam(ctx.url, "to");
        return from && to ? adherenceMixRange(from, to) : [];
      },
    },
  ],
});
