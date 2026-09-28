/**
 * Capture-owned visual-review sub-state seam (FTY-268).
 *
 * Registers `capture.barcode_granted`, `capture.label_guidance`, and
 * `capture.confirm_parsed` through FTY-247's registration API
 * (`registerVisualReviewPreset`) — the join contract the per-screen seam
 * stories (FTY-262..268) use to contribute a sub-state preset without editing
 * the shared registry (`e2e/visualReview/registry.ts`) or the in-scope
 * manifest (`e2e/visualReview/presets.ts`).
 *
 * The barcode scanner and label capture surfaces both sit behind Today's own
 * `scannerOpen` / `labelCaptureOpen` state (`useTodayData.ts`), opened only by
 * a composer press callback. Reaching `barcode_granted` also needs a granted
 * camera permission — but that mock already exists and already applies to
 * every E2E build: `state/cameraPermission.ts` swaps in
 * `e2eCameraPermissionsHook` whenever `isE2EMode()` is true (the simulator has
 * no camera — FTY-194), so both capture surfaces already render their granted
 * chrome with no visual-review-specific change. What's missing is only an
 * E2E-only *initial open state* so a surface is already showing when the
 * preset activates, instead of reachable only via a press —
 * `useActiveCaptureVisualReviewPreset` below is that seam.
 *
 * `capture.confirm_parsed` needs no camera at all: its initial-state seam
 * (wired in `useTodayData.ts`) drives the existing label-upload proposal flow
 * (`useLabelProposal.handleLabelUploaded`) with a synthetic already-uploaded
 * event, so the real `getLabelProposal` client call is answered by the mocked
 * fixture registered below — the same session/mock-fetch path a real upload
 * takes, minus the camera and the live backend.
 *
 * Everything here is inert outside `isE2EMode()`:
 * `useActiveCaptureVisualReviewPreset` checks the gate directly, and
 * registration itself only writes to an in-memory map that no code path reads
 * outside the `isE2EMode()`-gated deep-link route.
 */

import type { DailySummaryDTO } from "@/api/dailySummary";
import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import type { uploadLabelImage } from "@/api/labelCapture";
import type { LogEventDTO } from "@/api/logEvents";
import { E2E_SESSION } from "@/e2e/fixtures";
import { isE2EMode } from "@/e2e/launchMode";
import {
  registerVisualReviewPreset,
  useVisualReviewCore,
  type VisualReviewFetchContext,
  type VisualReviewResponse,
} from "@/e2e/visualReview";

export const CAPTURE_BARCODE_GRANTED_PRESET = "capture.barcode_granted";
export const CAPTURE_LABEL_GUIDANCE_PRESET = "capture.label_guidance";
export const CAPTURE_CONFIRM_PARSED_PRESET = "capture.confirm_parsed";
export const CAPTURE_LABEL_AUTO_UPLOAD_PRESET = "capture.label_auto_upload";

/**
 * Synthetic already-uploaded label event the `confirm_parsed` preset feeds
 * through the real label-proposal read (FTY-196/197) — no live upload, no
 * camera. Fabricated for testing only; carries no real user data.
 */
export const CAPTURE_CONFIRM_PARSED_EVENT: LogEventDTO = {
  id: "e2e-visual-review-capture-confirm-parsed-event",
  user_id: E2E_SESSION.userId,
  raw_text: "Nutrition label photo",
  name: null,
  status: "completed",
  created_at: "2026-01-01T12:00:00Z",
  updated_at: "2026-01-01T12:00:00Z",
};

/**
 * Synthetic uncounted parsed values the confirm-parsed-values sheet renders
 * (FTY-197). Fabricated for testing only; carries no real nutrition data.
 */
export const CAPTURE_CONFIRM_PARSED_PROPOSAL: DerivedFoodItemDTO = {
  item_type: "food",
  id: "e2e-visual-review-capture-confirm-parsed-item",
  user_id: E2E_SESSION.userId,
  log_event_id: CAPTURE_CONFIRM_PARSED_EVENT.id,
  name: "Granola bar",
  quantity_text: "1 bar",
  unit: "bar",
  amount: 1,
  status: "proposed",
  grams: 40,
  calories: 190,
  protein_g: 4,
  carbs_g: 29,
  fat_g: 7,
  calories_estimated: 190,
  protein_g_estimated: 4,
  carbs_g_estimated: 29,
  fat_g_estimated: 7,
  created_at: "2026-01-01T12:00:00Z",
  updated_at: "2026-01-01T12:00:00Z",
  source: { source_type: "user_label", label: "Label scan", ref: "user_label" },
};

/**
 * The committed, now-counted item the confirm POST returns (FTY-196): the same
 * synthetic parse flipped `proposed → resolved` so it counts. Fabricated for
 * testing only; carries no real nutrition data. Used to prove the confirm →
 * counted-on-Today acknowledgement through the injectable proposal seam when the
 * dogfood backend has no vision-capable provider (FTY-381) — no live upload, no
 * real proposal ever injected into a running backend.
 */
export const CAPTURE_CONFIRM_PARSED_COMMITTED: DerivedFoodItemDTO = {
  ...CAPTURE_CONFIRM_PARSED_PROPOSAL,
  status: "resolved",
  is_edited: false,
};

/** Zero-intake day behind the sheet before the parse is confirmed (hermetic). */
const CAPTURE_CONFIRM_PARSED_SUMMARY_UNCOUNTED: DailySummaryDTO = {
  date: "2026-01-01",
  intake: { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 },
  has_intake: false,
  uncounted_entries: 1,
  target: {
    calories: { effective: 2000, derived: 2000, source: "derived" },
    protein_g: { effective: 150, derived: 150, source: "derived" },
    carbs_g: { effective: 200, derived: 200, source: "derived" },
    fat_g: { effective: 65, derived: 65, source: "derived" },
  },
  exercise: { active_calories: 0 },
};

/** The same day AFTER the confirm — the parse now counts toward the hero/totals. */
const CAPTURE_CONFIRM_PARSED_SUMMARY_COUNTED: DailySummaryDTO = {
  ...CAPTURE_CONFIRM_PARSED_SUMMARY_UNCOUNTED,
  intake: { calories: 190, protein_g: 4, carbs_g: 29, fat_g: 7 },
  has_intake: true,
  uncounted_entries: 0,
};

/**
 * Whether the confirm POST has been received in this activation. The
 * daily-summary fixture reads it so Today's hero jumps from the uncounted day to
 * the counted one the moment the confirm commits — exactly what a real confirm
 * does (refetch the summary, FTY-196). Reset on each proposal read (the sheet
 * open) so re-activating the preset starts uncounted again. Module state, inert
 * outside `isE2EMode()` (nothing reads it there — the preset never activates).
 */
let confirmParsedCommitted = false;

/** Match the label-proposal GET for the synthetic confirm-parsed event. */
function isConfirmParsedProposalRead(
  ctx: VisualReviewFetchContext,
): boolean {
  return (
    ctx.method === "GET" &&
    ctx.pathEnd.endsWith(
      `/log-events/${CAPTURE_CONFIRM_PARSED_EVENT.id}/label-proposal`,
    )
  );
}

/** Match the confirm POST for the synthetic confirm-parsed event (FTY-196). */
function isConfirmParsedConfirmPost(ctx: VisualReviewFetchContext): boolean {
  return (
    ctx.method === "POST" &&
    ctx.pathEnd.endsWith(
      `/log-events/${CAPTURE_CONFIRM_PARSED_EVENT.id}/label-proposal/confirm`,
    )
  );
}

/**
 * The proposal + confirm + totals fixtures both confirm-gate presets share: the
 * uncounted parse the sheet renders, the confirm POST that commits it, and the
 * day totals that jump from 0 to the committed value once it lands. Shared so
 * `capture.label_auto_upload` (FTY-433) proves the *whole* shutter → upload →
 * confirm → counted path against exactly the fixtures `capture.confirm_parsed`
 * already pins for the sheet alone.
 */
function confirmGateResponses(): VisualReviewResponse[] {
  return [
    // The proposal read (sheet open): return the uncounted parse and reset the
    // committed flag so a re-activation always starts from the uncounted day.
    {
      match: isConfirmParsedProposalRead,
      body: () => {
        confirmParsedCommitted = false;
        return { proposal: CAPTURE_CONFIRM_PARSED_PROPOSAL };
      },
    },
    // The confirm POST ("Looks right"): commit the parse and return the resolved
    // item useLabelProposal swaps into the timeline as a counted row.
    {
      match: isConfirmParsedConfirmPost,
      body: () => {
        confirmParsedCommitted = true;
        return CAPTURE_CONFIRM_PARSED_COMMITTED;
      },
    },
    {
      match: (ctx) =>
        ctx.method === "GET" && ctx.pathEnd.endsWith("/log-events/by-date"),
      body: [] as unknown[],
    },
    // The hero/totals: uncounted before confirm, counted after — a pure function
    // of whether the confirm POST has landed this activation.
    {
      match: (ctx) =>
        ctx.method === "GET" && ctx.pathEnd.endsWith("/daily-summary"),
      body: () =>
        confirmParsedCommitted
          ? CAPTURE_CONFIRM_PARSED_SUMMARY_COUNTED
          : CAPTURE_CONFIRM_PARSED_SUMMARY_UNCOUNTED,
    },
  ];
}

registerVisualReviewPreset({
  name: CAPTURE_BARCODE_GRANTED_PRESET,
  route: "/",
  settledPath: "/",
});

registerVisualReviewPreset({
  name: CAPTURE_LABEL_GUIDANCE_PRESET,
  route: "/",
  settledPath: "/",
});

registerVisualReviewPreset({
  name: CAPTURE_CONFIRM_PARSED_PRESET,
  route: "/",
  settledPath: "/",
  responses: [
    // The event feed behind the sheet: the single completed label event, so the
    // seam-injected row is never wiped by the initial load and persists as a
    // counted row after confirm. Kept a `completed` event so Today never polls
    // it away (polling is gated on pending work).
    {
      match: (ctx) =>
        ctx.method === "GET" && ctx.pathEnd.endsWith("/log-events"),
      body: [CAPTURE_CONFIRM_PARSED_EVENT],
    },
    ...confirmGateResponses(),
  ],
});

registerVisualReviewPreset({
  name: CAPTURE_LABEL_AUTO_UPLOAD_PRESET,
  route: "/",
  settledPath: "/",
  responses: [
    // An empty day behind the capture surface: unlike `confirm_parsed` (which
    // seeds the event at mount), here the label event arrives *from the upload*,
    // so pre-seeding the feed would duplicate the row the auto-upload inserts.
    {
      match: (ctx) =>
        ctx.method === "GET" && ctx.pathEnd.endsWith("/log-events"),
      body: [] as unknown[],
    },
    ...confirmGateResponses(),
  ],
});

/** The capture sub-state presets this module registers, or `null`. */
export type CaptureVisualReviewPreset =
  | typeof CAPTURE_BARCODE_GRANTED_PRESET
  | typeof CAPTURE_LABEL_GUIDANCE_PRESET
  | typeof CAPTURE_CONFIRM_PARSED_PRESET
  | typeof CAPTURE_LABEL_AUTO_UPLOAD_PRESET
  | null;

/**
 * The active capture sub-state preset, or `null` when none is active or
 * outside `isE2EMode()`. `useTodayData` reads this once at mount to compute
 * the initial open state for the scanner / label-capture modals and to seed
 * the confirm-parsed proposal. Checking `isE2EMode()` directly (rather than
 * relying on the registry only ever being activated in E2E mode) keeps this
 * seam inert even if a release build somehow carried a stale active-preset
 * snapshot.
 */
export function useActiveCaptureVisualReviewPreset(): CaptureVisualReviewPreset {
  const core = useVisualReviewCore();
  if (!isE2EMode()) return null;
  switch (core.presetName) {
    case CAPTURE_BARCODE_GRANTED_PRESET:
    case CAPTURE_LABEL_GUIDANCE_PRESET:
    case CAPTURE_CONFIRM_PARSED_PRESET:
    case CAPTURE_LABEL_AUTO_UPLOAD_PRESET:
      return core.presetName;
    default:
      return null;
  }
}

// ─── Label auto-upload seam (FTY-433) ────────────────────────────────────────

/**
 * The frame the auto-upload preset's `takePhoto` seam returns. The iOS simulator
 * has no camera, so `takePictureAsync` can't produce a shot; this stands in as
 * the one the shutter takes.
 *
 * It is a tiny (24×40, ~100 byte) greyscale PNG drawn to read as a
 * nutrition-label card — a dark title bar over pale value rows — so the uploading
 * state's held-frame backdrop is *visibly* the captured photo in running-app
 * evidence, which a transparent placeholder could not show. Fabricated for
 * testing only: synthetic pixels, no real label and no real image.
 */
export const CAPTURE_LABEL_PHOTO_URI =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAABgAAAAoCAAAAADBZmWJAAAALElEQVR42mM4gQMwnDjxGgsAS9hgAdSWwGk5GRIVGOD1qB2jdlBsx6CUwA4AusTu01y6fVUAAAAASUVORK5CYII=";

/**
 * How long the seam's upload is held in flight. Sized for the *driver*, not for
 * realism: each Maestro command on iOS costs a few seconds of accessibility-tree
 * latency, so a short hold lets the upload resolve between "assert Uploading" and
 * "tap Retake" — the shutter→Retake race that made the retake evidence flow
 * flaky. A generous hold makes both evidence flows deterministic: the uploading
 * state (held frame + Retake) is a stable surface to screenshot, a Retake tap
 * genuinely lands mid-upload, and the superseded result still arrives afterwards
 * so a flow can prove it is dropped.
 */
export const CAPTURE_LABEL_AUTO_UPLOAD_HOLD_MS = 25_000;

/** The synthetic shutter frame for `capture.label_auto_upload`. */
async function e2eLabelTakePhoto(): Promise<{ uri: string }> {
  return { uri: CAPTURE_LABEL_PHOTO_URI };
}

/**
 * The synthetic label upload for `capture.label_auto_upload`. The real client
 * streams the image bytes through native networking (`File.upload`, FTY-381),
 * which the E2E fetch mock cannot intercept, so the upload itself is the seam:
 * it holds for {@link CAPTURE_LABEL_AUTO_UPLOAD_HOLD_MS} and then resolves with
 * the same synthetic label event `capture.confirm_parsed` pins, handing the real
 * `handleLabelUploaded` → proposal-read → confirm-sheet path its normal input.
 */
const e2eUploadLabel: typeof uploadLabelImage = async () => {
  await new Promise((resolve) =>
    setTimeout(resolve, CAPTURE_LABEL_AUTO_UPLOAD_HOLD_MS),
  );
  return CAPTURE_CONFIRM_PARSED_EVENT;
};

/** Capture seams a preset can substitute for the real camera/upload clients. */
export interface CaptureVisualReviewInjectables {
  readonly labelTakePhoto?: () => Promise<{ uri: string }>;
  readonly uploadLabel?: typeof uploadLabelImage;
}

/** No seams — every preset except the auto-upload one, and every real launch. */
const NO_CAPTURE_INJECTABLES: CaptureVisualReviewInjectables = {};

const LABEL_AUTO_UPLOAD_INJECTABLES: CaptureVisualReviewInjectables = {
  labelTakePhoto: e2eLabelTakePhoto,
  uploadLabel: e2eUploadLabel,
};

/**
 * The capture seams a preset installs: none for every preset but
 * `capture.label_auto_upload` (and none for `null`, which is what every real
 * launch and every non-E2E build resolves to). Returns module constants, so this
 * never churns a consumer's render.
 */
export function captureVisualReviewInjectables(
  preset: CaptureVisualReviewPreset,
): CaptureVisualReviewInjectables {
  return preset === CAPTURE_LABEL_AUTO_UPLOAD_PRESET
    ? LABEL_AUTO_UPLOAD_INJECTABLES
    : NO_CAPTURE_INJECTABLES;
}

/**
 * The capture seams the *active* preset installs — what TodayScreen reads.
 * Inert outside `isE2EMode()`, where the active preset is always `null`, so a
 * release build always uses the real camera and the real upload client.
 */
export function useCaptureVisualReviewInjectables(): CaptureVisualReviewInjectables {
  return captureVisualReviewInjectables(useActiveCaptureVisualReviewPreset());
}
