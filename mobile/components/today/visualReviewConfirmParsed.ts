/**
 * `today.confirm_parsed` visual-review preset (FTY-262).
 *
 * Today's parsed-confirmation sub-state (the {@link ConfirmParsedValuesSheet}
 * shown by `useLabelProposal`, FTY-196/197) is component-local `useState` — no
 * route param, opened only via the label-capture upload callback. FTY-247 left
 * such sub-states unregistered on purpose (see its README's "Deferred sub-state
 * presets"); this module is the Today-owned plug-in the join contract expects:
 * it registers the preset through {@link registerVisualReviewPreset} (never
 * editing the shared registry/manifest) and exports the synthetic fixture +
 * preset name `useLabelProposal` reads to seed its initial state.
 *
 * Registration runs unconditionally at module load (mirroring `presets.ts`) —
 * cheap, and inert on its own: the preset only becomes *reachable* through the
 * `isE2EMode()`-gated deep-link route (`app/__visual-review.tsx`) and the
 * `isE2EMode()` check `useLabelProposal` applies before ever reading it.
 *
 * All fixture data is synthetic — no real user, body, or nutrition data.
 */

import type { DailySummaryDTO } from "@/api/dailySummary";
import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import {
  registerVisualReviewPreset,
  type VisualReviewFetchContext,
} from "@/e2e/visualReview";

/** The deep-link preset name: `fatty://__visual-review?preset=today.confirm_parsed`. */
export const CONFIRM_PARSED_PRESET_NAME = "today.confirm_parsed";

const EVENT_ID = "e2e-confirm-parsed-event-00000000-0000-0000-0000-000000000000";
const USER_ID = "e2e-user-00000000-0000-0000-0000-000000000000";

/**
 * The uncounted label parse the confirm sheet presents. Mirrors the shape a real
 * legible label upload produces (`user_label` / "Label scan" provenance, status
 * `proposed`) so the visual audit sees an authentic sub-state.
 */
export const CONFIRM_PARSED_ITEM: DerivedFoodItemDTO = {
  item_type: "food",
  id: "e2e-confirm-parsed-item-00000000-0000-0000-0000-000000000000",
  user_id: USER_ID,
  log_event_id: EVENT_ID,
  name: "Granola bar",
  quantity_text: "1 bar",
  unit: "bar",
  amount: 1,
  status: "proposed",
  grams: null,
  calories: 190,
  protein_g: 4,
  carbs_g: 29,
  fat_g: 7,
  calories_estimated: 190,
  protein_g_estimated: 4,
  carbs_g_estimated: 29,
  fat_g_estimated: 7,
  created_at: "2026-01-01T09:00:00Z",
  updated_at: "2026-01-01T09:00:00Z",
  source: { source_type: "user_label", label: "Label scan", ref: "user_label" },
  is_edited: false,
};

/** Zero-intake day behind the sheet — hermetic regardless of prior flow state in a shared binary (mirrors `today.empty`). */
const CONFIRM_PARSED_SUMMARY: DailySummaryDTO = {
  date: "2026-01-01",
  intake: { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 },
  has_intake: false,
  uncounted_entries: 0,
  target: {
    calories: { effective: 2000, derived: 2000, source: "derived" },
    protein_g: { effective: 150, derived: 150, source: "derived" },
    carbs_g: { effective: 200, derived: 200, source: "derived" },
    fat_g: { effective: 65, derived: 65, source: "derived" },
  },
  exercise: { active_calories: 0 },
};

const EMPTY_LIST: unknown[] = [];

/** Match a GET request whose path ends with `suffix`. */
function get(suffix: string): (ctx: VisualReviewFetchContext) => boolean {
  return (ctx) => ctx.method === "GET" && ctx.pathEnd.endsWith(suffix);
}

// The confirm sheet's own values come from the E2E-only initial-state seam
// (useLabelProposal), never a fetch — there is no route/fixture path to it. The
// background timeline behind the sheet is still seeded through the mock-fetch
// mechanism, kept an explicit empty day so the screenshot is hermetic
// regardless of any prior preset's state in a shared E2E binary.
registerVisualReviewPreset({
  name: CONFIRM_PARSED_PRESET_NAME,
  route: "/",
  settledPath: "/",
  responses: [
    { match: get("/log-events/by-date"), body: EMPTY_LIST },
    { match: get("/log-events"), body: EMPTY_LIST },
    { match: get("/daily-summary"), body: CONFIRM_PARSED_SUMMARY },
  ],
});
