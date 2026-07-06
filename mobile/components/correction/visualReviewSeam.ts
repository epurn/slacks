/**
 * FTY-263: Visual-review seam for the correction sheet's sub-states.
 *
 * The correction sheet's `detail` (normal), `typeahead` (change-match), and
 * `confirm_apply` (override) modes are component-local state opened only by a
 * press callback (`CorrectionSheet` mounts from
 * `components/today/TodaySheetHost.tsx`) — there is no route param or
 * initial-state prop that reaches them, so FTY-247's visual-review harness
 * cannot open them on its own. This module is the correction-owned seam that
 * closes that gap:
 *
 *   - it registers three presets — `correction.detail`, `correction.typeahead`,
 *     `correction.confirm_apply` — through FTY-247's registration API
 *     ({@link registerVisualReviewPreset}), from correction-owned code, without
 *     editing the shared registry or `presets.ts`;
 *   - it exposes {@link useCorrectionVisualReviewSeam}, which Today's sheet
 *     wiring (`components/today/useTodayData.ts`) reads to open the sheet
 *     directly in the requested mode over a synthetic resolved entry — never a
 *     scripted tap.
 *
 * Everything here is inert outside `isE2EMode()`: the hook returns `null`
 * unconditionally when it is false, even if a preset were somehow active (it
 * cannot be — activation only happens through the `isE2EMode()`-gated deep-link
 * route), and registration itself carries no secrets or auth state (same as
 * FTY-247's own `presets.ts`, which registers unconditionally at import time).
 */

import type { DerivedItem } from "@/api/derivedItems";
import {
  E2E_CORRECTION_ENTRY,
  E2E_CORRECTION_EVENT,
  E2E_CORRECTION_ITEM,
  E2E_CORRECTION_RAW_TEXT,
  E2E_CORRECTION_SUMMARY,
} from "@/e2e/fixtures";
import { isE2EMode } from "@/e2e/launchMode";
import {
  registerVisualReviewPreset,
  useVisualReviewCore,
  type VisualReviewFetchContext,
} from "@/e2e/visualReview";

import type { SheetMode } from "./useCorrectionSheet";

/** Match a GET request whose path ends with `suffix`. */
function get(suffix: string): (ctx: VisualReviewFetchContext) => boolean {
  return (ctx) => ctx.method === "GET" && ctx.pathEnd.endsWith(suffix);
}

/** Maps each seam preset name to the correction-sheet mode it opens into. */
const PRESET_MODES: Readonly<Record<string, SheetMode>> = {
  "correction.detail": "normal",
  "correction.typeahead": "change-match",
  "correction.confirm_apply": "override",
};

// Each preset seeds the same synthetic resolved "Oatmeal" entry (already used
// by correction.yaml/correction-beat.yaml) so the sheet always has real,
// evidence-carrying data to open over — hermetic regardless of any other
// flow's fixture-machine stage, just like FTY-247's own today.populated/empty.
for (const name of Object.keys(PRESET_MODES)) {
  registerVisualReviewPreset({
    name,
    route: "/",
    settledPath: "/",
    responses: [
      { match: get("/log-events/by-date"), body: [E2E_CORRECTION_ENTRY] },
      { match: get("/log-events"), body: [E2E_CORRECTION_EVENT] },
      { match: get("/daily-summary"), body: E2E_CORRECTION_SUMMARY },
    ],
  });
}

/** The correction sheet's seam target: what to open, and in which mode. */
export interface CorrectionVisualReviewSeam {
  readonly presetName: string;
  readonly item: DerivedItem;
  readonly logPhrase: string;
  readonly mode: SheetMode;
}

/**
 * The active correction seam, or `null` when no `correction.*` preset is
 * active — including always outside `isE2EMode()`, where the visual-review
 * core never activates. Today's sheet wiring opens the sheet over the
 * synthetic oatmeal entry directly in the requested mode when this is non-null.
 */
export function useCorrectionVisualReviewSeam(): CorrectionVisualReviewSeam | null {
  const core = useVisualReviewCore();
  if (!isE2EMode()) return null;
  const presetName = core.presetName;
  const mode = presetName ? PRESET_MODES[presetName] : undefined;
  if (!presetName || !mode) return null;
  return { presetName, item: E2E_CORRECTION_ITEM, logPhrase: E2E_CORRECTION_RAW_TEXT, mode };
}
