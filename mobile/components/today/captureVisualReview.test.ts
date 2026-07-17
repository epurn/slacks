/**
 * Capture-owned visual-review preset tests (FTY-268).
 *
 * Proves the three capture sub-state presets are registered through FTY-247's
 * registration API (no shared registry/manifest edit — importing this module
 * is the only side effect) and that activating `capture.confirm_parsed` makes
 * the real `getLabelProposal` client resolve the synthetic parsed values
 * through the registered fixture, the same session/mock-fetch path a real
 * label upload takes.
 */

// Importing the module under test registers the presets as a side effect.
import {
  CAPTURE_BARCODE_GRANTED_PRESET,
  CAPTURE_CONFIRM_PARSED_COMMITTED,
  CAPTURE_CONFIRM_PARSED_EVENT,
  CAPTURE_CONFIRM_PARSED_PRESET,
  CAPTURE_CONFIRM_PARSED_PROPOSAL,
  CAPTURE_LABEL_GUIDANCE_PRESET,
} from "./captureVisualReview";

import { activateVisualReviewPreset, getVisualReviewPreset } from "@/e2e/visualReview";
import { __deactivateVisualReview } from "@/e2e/visualReview/session";
import { createE2EMockFetch } from "@/e2e/launchMode";
import { E2E_SESSION } from "@/e2e/fixtures";
import { toApiSession } from "@/state/session";
import { getDailySummary } from "@/api/dailySummary";
import {
  confirmLabelProposal,
  getLabelProposal,
  LabelProposalApiError,
} from "@/api/labelProposal";

const apiSession = toApiSession(E2E_SESSION);

afterEach(() => {
  __deactivateVisualReview();
});

describe("capture sub-state preset registration", () => {
  it("registers capture.barcode_granted with a route + settledPath", () => {
    const preset = getVisualReviewPreset(CAPTURE_BARCODE_GRANTED_PRESET);
    expect(preset).toBeDefined();
    expect(preset?.route).toBe("/");
    expect(preset?.settledPath).toBe("/");
  });

  it("registers capture.label_guidance with a route + settledPath", () => {
    const preset = getVisualReviewPreset(CAPTURE_LABEL_GUIDANCE_PRESET);
    expect(preset).toBeDefined();
    expect(preset?.route).toBe("/");
    expect(preset?.settledPath).toBe("/");
  });

  it("registers capture.confirm_parsed with a route + settledPath", () => {
    const preset = getVisualReviewPreset(CAPTURE_CONFIRM_PARSED_PRESET);
    expect(preset).toBeDefined();
    expect(preset?.route).toBe("/");
    expect(preset?.settledPath).toBe("/");
  });
});

describe("capture.confirm_parsed seeds the real label-proposal read", () => {
  it("makes getLabelProposal resolve the synthetic parsed values for the seam's event", async () => {
    activateVisualReviewPreset(CAPTURE_CONFIRM_PARSED_PRESET, null);
    const mockFetch = createE2EMockFetch();
    await expect(
      getLabelProposal(apiSession, CAPTURE_CONFIRM_PARSED_EVENT.id, mockFetch),
    ).resolves.toEqual(CAPTURE_CONFIRM_PARSED_PROPOSAL);
  });

  it("is inert until activated: an unrelated preset leaves the read on the default 404 fallback", async () => {
    activateVisualReviewPreset(CAPTURE_BARCODE_GRANTED_PRESET, null);
    const mockFetch = createE2EMockFetch();
    await expect(
      getLabelProposal(apiSession, CAPTURE_CONFIRM_PARSED_EVENT.id, mockFetch),
    ).rejects.toBeInstanceOf(LabelProposalApiError);
  });

  it("does not answer a label-proposal read for a different event id", async () => {
    activateVisualReviewPreset(CAPTURE_CONFIRM_PARSED_PRESET, null);
    const mockFetch = createE2EMockFetch();
    await expect(
      getLabelProposal(apiSession, "some-other-event-id", mockFetch),
    ).rejects.toBeInstanceOf(LabelProposalApiError);
  });
});

describe("capture.confirm_parsed proves confirm → counted through the seam (FTY-381)", () => {
  it("returns the resolved committed item from the confirm POST", async () => {
    activateVisualReviewPreset(CAPTURE_CONFIRM_PARSED_PRESET, null);
    const mockFetch = createE2EMockFetch();
    await expect(
      confirmLabelProposal(
        apiSession,
        CAPTURE_CONFIRM_PARSED_EVENT.id,
        {},
        mockFetch,
      ),
    ).resolves.toEqual(CAPTURE_CONFIRM_PARSED_COMMITTED);
    expect(CAPTURE_CONFIRM_PARSED_COMMITTED.status).toBe("resolved");
  });

  it("flips the daily summary from uncounted to counted once the confirm POST lands", async () => {
    activateVisualReviewPreset(CAPTURE_CONFIRM_PARSED_PRESET, null);
    const mockFetch = createE2EMockFetch();

    // Reading the proposal (the sheet open) resets the seam to the uncounted day.
    await getLabelProposal(apiSession, CAPTURE_CONFIRM_PARSED_EVENT.id, mockFetch);
    const before = await getDailySummary(apiSession, undefined, mockFetch);
    expect(before.intake.calories).toBe(0);
    expect(before.has_intake).toBe(false);

    // Confirming ("Looks right") commits the parse; the hero now counts it.
    await confirmLabelProposal(
      apiSession,
      CAPTURE_CONFIRM_PARSED_EVENT.id,
      {},
      mockFetch,
    );
    const after = await getDailySummary(apiSession, undefined, mockFetch);
    expect(after.intake.calories).toBe(190);
    expect(after.has_intake).toBe(true);
  });
});
