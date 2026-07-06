/**
 * Trends-owned visual-review preset tests (FTY-264).
 *
 * Proves `trends.adherence_retry` is registered through FTY-247's registration
 * API and that activating it makes the real `getDailySummaryRange` client throw
 * (the same rejection TrendsScreen's adherence card treats as its error/retry
 * state) while leaving `listWeightEntries` on the default populated fixture —
 * so only the adherence card, not the whole screen, renders a failure.
 */

// Importing the module under test registers the preset as a side effect.
import "./visualReviewPresets";

import {
  activateVisualReviewPreset,
  getVisualReviewPreset,
} from "@/e2e/visualReview";
import { __deactivateVisualReview } from "@/e2e/visualReview/session";
import { createE2EMockFetch } from "@/e2e/launchMode";
import { E2E_SESSION } from "@/e2e/fixtures";
import { toApiSession } from "@/state/session";
import { getDailySummaryRange, DailySummaryApiError } from "@/api/dailySummary";
import { listWeightEntries } from "@/api/weightEntries";

const apiSession = toApiSession(E2E_SESSION);
const to = "2026-06-29";
const from = "2026-06-01";

afterEach(() => {
  __deactivateVisualReview();
});

describe("trends.adherence_retry registration", () => {
  it("is registered through the FTY-247 API with a route + settledPath", () => {
    const preset = getVisualReviewPreset("trends.adherence_retry");
    expect(preset).toBeDefined();
    expect(preset?.route).toBe("/trends");
    expect(preset?.settledPath).toBe("/trends");
  });

  it("is inert until activated: an unrelated preset leaves the range read on its default", async () => {
    activateVisualReviewPreset("trends.populated", null);
    const mockFetch = createE2EMockFetch();
    await expect(
      getDailySummaryRange(apiSession, from, to, mockFetch),
    ).resolves.not.toHaveLength(0);
  });
});

describe("trends.adherence_retry seeds a range-read failure through the real client", () => {
  it("makes getDailySummaryRange reject with a DailySummaryApiError", async () => {
    activateVisualReviewPreset("trends.adherence_retry", null);
    const mockFetch = createE2EMockFetch();
    await expect(
      getDailySummaryRange(apiSession, from, to, mockFetch),
    ).rejects.toBeInstanceOf(DailySummaryApiError);
  });

  it("leaves the weight card's series on the default populated fixture", async () => {
    activateVisualReviewPreset("trends.adherence_retry", null);
    const mockFetch = createE2EMockFetch();
    const entries = await listWeightEntries(apiSession, from, to, mockFetch);
    expect(entries.length).toBeGreaterThan(0);
  });
});
