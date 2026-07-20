/**
 * FTY-263 / FTY-313: Visual-review seam for the correction sheet's sub-states.
 *
 * The correction sheet's `detail` (normal), `typeahead` (change-match),
 * `confirm_apply` (override), and `Make it exact` (make-exact) modes are
 * component-local state opened only by a press callback (`CorrectionSheet`
 * mounts from `components/today/TodaySheetHost.tsx`) — there is no route param or
 * initial-state prop that reaches them, so FTY-247's visual-review harness
 * cannot open them on its own. This module is the correction-owned seam that
 * closes that gap:
 *
 *   - it registers the correction presets — `correction.detail`,
 *     `correction.typeahead`, `correction.confirm_apply` (FTY-263) plus the
 *     `Make it exact` audit presets `correction.exact_eligible`,
 *     `correction.exact_choose`, `correction.exact_barcode_exact`,
 *     `correction.exact_barcode_fallback`, `correction.exact_no_proposal`,
 *     `correction.exact_label`, and `correction.exact_applied` (FTY-313), plus
 *     `correction.prior_correction` (FTY-407), the change-match panel for an item
 *     whose name the user has corrected before —
 *     through FTY-247's registration API ({@link registerVisualReviewPreset}),
 *     from correction-owned code, without editing the shared registry or
 *     `presets.ts`;
 *   - it exposes {@link useCorrectionVisualReviewSeam}, which Today's sheet
 *     wiring (`components/today/useTodayData.ts`) reads to open the sheet
 *     directly in the requested mode over the preset's synthetic entry — never a
 *     scripted tap. For the exact-flow presets it also carries an
 *     {@link ExactEvidenceSeed} that opens the sub-flow straight in its settled
 *     sub-step (choose / preview / error / label-open), because at the
 *     make-exact sheet's large, dimmed detent iOS exposes no in-modal content to
 *     drive with a scripted tap (ratified FTY-272).
 *
 * Everything here is inert outside `isE2EMode()`: the hook returns `null`
 * unconditionally when it is false, even if a preset were somehow active (it
 * cannot be — activation only happens through the `isE2EMode()`-gated deep-link
 * route), and registration itself carries no secrets or auth state (same as
 * FTY-247's own `presets.ts`, which registers unconditionally at import time).
 */

import type { DerivedFoodItemDTO, DerivedItem } from "@/api/derivedItems";
import type { DailySummaryDTO } from "@/api/dailySummary";
import type { LogEventDTO, LogEventEntryDTO } from "@/api/logEvents";
import {
  E2E_CORRECTION_ENTRY,
  E2E_CORRECTION_EVENT,
  E2E_CORRECTION_ITEM,
  E2E_CORRECTION_RAW_TEXT,
  E2E_CORRECTION_SUMMARY,
  E2E_PRIOR_CORRECTION_APPLIED_ITEM,
  E2E_PRIOR_CORRECTION_CANDIDATE,
  E2E_SOURCE_CANDIDATE,
} from "@/e2e/fixtures";
import {
  E2E_EXACT_APPLIED_ENTRY,
  E2E_EXACT_APPLIED_ITEM,
  E2E_EXACT_APPLIED_SUMMARY,
  E2E_EXACT_BARCODE_EXACT_PROPOSAL,
  E2E_EXACT_BARCODE_FALLBACK_PROPOSAL,
  E2E_EXACT_ELIGIBLE_ENTRY,
  E2E_EXACT_ELIGIBLE_ITEM,
  E2E_EXACT_ELIGIBLE_SUMMARY,
  E2E_EXACT_EVENT,
  E2E_EXACT_LABEL_PHOTO_URI,
  E2E_EXACT_NO_PROPOSAL_MESSAGE,
  E2E_EXACT_RAW_TEXT,
} from "@/e2e/exactEvidenceFixtures";
import { isE2EMode } from "@/e2e/launchMode";
import {
  registerVisualReviewPreset,
  useVisualReviewCore,
  type VisualReviewFetchContext,
  type VisualReviewResponse,
} from "@/e2e/visualReview";

import type { ExactEvidenceCaptureInjectables } from "./ExactEvidencePanel";
import type { SheetMode } from "./useCorrectionSheet";
import type { ExactEvidenceSeed } from "./useExactEvidence";

/** Match a GET request whose path ends with `suffix`. */
function get(suffix: string): (ctx: VisualReviewFetchContext) => boolean {
  return (ctx) => ctx.method === "GET" && ctx.pathEnd.endsWith(suffix);
}

/** Match a POST request whose path ends with `suffix` (FTY-407). */
function post(suffix: string): (ctx: VisualReviewFetchContext) => boolean {
  return (ctx) => ctx.method === "POST" && ctx.pathEnd.endsWith(suffix);
}

/** The label-capture `takePhoto` seam for `correction.exact_label`: the camera-less
 *  simulator can't shoot a real photo, so return a synthetic image URI. */
async function e2eLabelTakePhoto(): Promise<{ uri: string }> {
  return { uri: E2E_EXACT_LABEL_PHOTO_URI };
}

/** One correction seam preset: what to open, in which mode, over which entry. */
interface SeamPreset {
  readonly mode: SheetMode;
  readonly item: DerivedFoodItemDTO;
  readonly rawText: string;
  readonly entry: LogEventEntryDTO;
  readonly event: LogEventDTO;
  readonly summary: DailySummaryDTO;
  /** FTY-313: opens the make-exact sub-flow straight in a settled sub-step. */
  readonly exactSeed?: ExactEvidenceSeed;
  /** FTY-313: injected `takePhoto` for the label-capture-from-correction shot. */
  readonly labelTakePhoto?: () => Promise<{ uri: string }>;
  /**
   * FTY-407: extra fetch overrides this preset alone installs, on top of the
   * shared entry/event/summary seeds every correction preset gets. Scoping them
   * per-preset is what lets `correction.prior_correction` seed a
   * `prior_corrections` list without changing the shared E2E mock — and so
   * without changing what `correction.typeahead` renders.
   */
  readonly responses?: readonly VisualReviewResponse[];
}

/** A trusted-item preset (FTY-263) over the shared synthetic Oatmeal entry. */
function correctionPreset(mode: SheetMode): SeamPreset {
  return {
    mode,
    item: E2E_CORRECTION_ITEM,
    rawText: E2E_CORRECTION_RAW_TEXT,
    entry: E2E_CORRECTION_ENTRY,
    event: E2E_CORRECTION_EVENT,
    summary: E2E_CORRECTION_SUMMARY,
  };
}

/** A make-exact preset (FTY-313) over the low-trust, exact-upgrade-eligible item. */
function eligibleExactPreset(
  extra: Pick<SeamPreset, "exactSeed" | "labelTakePhoto"> = {},
): SeamPreset {
  return {
    mode: "make-exact",
    item: E2E_EXACT_ELIGIBLE_ITEM,
    rawText: E2E_EXACT_RAW_TEXT,
    entry: E2E_EXACT_ELIGIBLE_ENTRY,
    event: E2E_EXACT_EVENT,
    summary: E2E_EXACT_ELIGIBLE_SUMMARY,
    ...extra,
  };
}

/** Every correction seam preset, keyed by its visual-review preset name. */
const PRESETS: Readonly<Record<string, SeamPreset>> = {
  // FTY-263: the three original correction sub-states over the trusted item.
  "correction.detail": correctionPreset("normal"),
  "correction.typeahead": correctionPreset("change-match"),
  "correction.confirm_apply": correctionPreset("override"),

  // FTY-407: the same change-match panel, but for an item whose normalized name
  // the user has corrected before — so FTY-411's `prior_corrections` list is
  // non-empty and the panel shows a "Your corrections" group ranked above the
  // guessed USDA match. Seeded here rather than in the shared E2E mock so
  // `correction.typeahead` above keeps rendering the guessed-only list it always
  // has (its screenshots are the no-history control for this one).
  //
  // The seeded `/re-resolve` answers with the applied prior correction: in this
  // preset the only pickable history row is that one, so the response needs no
  // body inspection (preset matchers see method + path only).
  "correction.prior_correction": {
    ...correctionPreset("change-match"),
    responses: [
      {
        match: post("/source-candidates"),
        body: {
          candidates: [E2E_SOURCE_CANDIDATE],
          prior_corrections: [E2E_PRIOR_CORRECTION_CANDIDATE],
        },
      },
      {
        match: post("/re-resolve"),
        body: E2E_PRIOR_CORRECTION_APPLIED_ITEM,
      },
    ],
  },

  // FTY-313 `Make it exact` audit presets.
  // Normal detail sheet on a low-trust item: the `Make it exact` nudge is visible.
  "correction.exact_eligible": {
    mode: "normal",
    item: E2E_EXACT_ELIGIBLE_ITEM,
    rawText: E2E_EXACT_RAW_TEXT,
    entry: E2E_EXACT_ELIGIBLE_ENTRY,
    event: E2E_EXACT_EVENT,
    summary: E2E_EXACT_ELIGIBLE_SUMMARY,
  },
  // The exact-evidence choice surface (scan / type / capture label / cancel).
  "correction.exact_choose": eligibleExactPreset({ exactSeed: { step: "choose" } }),
  // A typed-barcode exact proposal preview (trusted "Exact match · …").
  "correction.exact_barcode_exact": eligibleExactPreset({
    exactSeed: { step: "preview", proposal: E2E_EXACT_BARCODE_EXACT_PROPOSAL },
  }),
  // A typed-barcode fallback proposal preview ("≈ Rough fallback", not exact).
  "correction.exact_barcode_fallback": eligibleExactPreset({
    exactSeed: { step: "preview", proposal: E2E_EXACT_BARCODE_FALLBACK_PROPOSAL },
  }),
  // The no-proposal/error state — calm, actionable, item unchanged.
  "correction.exact_no_proposal": eligibleExactPreset({
    exactSeed: { step: "error", error: E2E_EXACT_NO_PROPOSAL_MESSAGE },
  }),
  // The label-capture surface presented from the correction flow, with the
  // injected `takePhoto` so the save-photo (default off) preview is reachable.
  "correction.exact_label": eligibleExactPreset({
    exactSeed: { step: "choose", labelOpen: true },
    labelTakePhoto: e2eLabelTakePhoto,
  }),
  // The applied end state: the same item, now source-backed (Open Food Facts),
  // `Make it exact` gone; the timeline behind shows one row, not a duplicate.
  "correction.exact_applied": {
    mode: "normal",
    item: E2E_EXACT_APPLIED_ITEM,
    rawText: E2E_EXACT_RAW_TEXT,
    entry: E2E_EXACT_APPLIED_ENTRY,
    event: E2E_EXACT_EVENT,
    summary: E2E_EXACT_APPLIED_SUMMARY,
  },
};

// Each preset seeds its own synthetic entry so the sheet always has real,
// evidence-carrying data to open over — hermetic regardless of any other flow's
// fixture-machine stage, just like FTY-247's own today.populated/empty.
for (const [name, preset] of Object.entries(PRESETS)) {
  registerVisualReviewPreset({
    name,
    route: "/",
    settledPath: "/",
    responses: [
      // Preset-specific overrides go first: `resolveVisualReviewFetch` answers
      // with the first match, so these win over both the shared seeds below and
      // the default E2E mock (FTY-407).
      ...(preset.responses ?? []),
      { match: get("/log-events/by-date"), body: [preset.entry] },
      { match: get("/log-events"), body: [preset.event] },
      { match: get("/daily-summary"), body: preset.summary },
    ],
  });
}

/** The correction sheet's seam target: what to open, and in which mode. */
export interface CorrectionVisualReviewSeam {
  readonly presetName: string;
  readonly item: DerivedItem;
  readonly logPhrase: string;
  readonly mode: SheetMode;
  /**
   * The `visual-review-settled:<preset>` testID the sheet renders inside its
   * modal subtree once the mode's async state settles (see CorrectionSheet's
   * `settledMarkerTestID`). This is the marker screenshot automation waits on —
   * the navigator-level overlay is occluded behind the presented sheet.
   */
  readonly settledMarkerTestID: string;
  /**
   * FTY-313: for a make-exact preset, the seed opening the sub-flow directly in
   * its settled sub-step; `undefined` for the FTY-263 presets.
   */
  readonly exactSeed?: ExactEvidenceSeed;
  /** FTY-313: injected capture seams (the label `takePhoto`) for `exact_label`. */
  readonly exactCapture?: ExactEvidenceCaptureInjectables;
}

/**
 * The active correction seam, or `null` when no `correction.*` preset is
 * active — including always outside `isE2EMode()`, where the visual-review
 * core never activates. Today's sheet wiring opens the sheet over the
 * preset's synthetic entry directly in the requested mode when this is non-null.
 */
export function useCorrectionVisualReviewSeam(): CorrectionVisualReviewSeam | null {
  const core = useVisualReviewCore();
  if (!isE2EMode()) return null;
  const presetName = core.presetName;
  const preset = presetName ? PRESETS[presetName] : undefined;
  if (!presetName || !preset) return null;
  return {
    presetName,
    item: preset.item,
    logPhrase: preset.rawText,
    mode: preset.mode,
    settledMarkerTestID: `visual-review-settled:${presetName}`,
    exactSeed: preset.exactSeed,
    exactCapture: preset.labelTakePhoto
      ? { labelTakePhoto: preset.labelTakePhoto }
      : undefined,
  };
}
