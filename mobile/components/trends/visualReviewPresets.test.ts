/**
 * Trends-owned visual-review preset tests (FTY-264, FTY-431).
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
import { computeAdherence } from "@/state/trends";

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

// FTY-431: the off-target restyle's evidence needs one strip that shows every
// cell state at once. This proves the preset's fixture actually classifies into
// all four states through the real range client + the real strip derivation —
// so a screenshot of it can't quietly be missing the states it claims to show.
describe("trends.adherence_mix seeds a strip covering all four cell states", () => {
  it("is registered through the FTY-247 API with a route + settledPath", () => {
    const preset = getVisualReviewPreset("trends.adherence_mix");
    expect(preset).toBeDefined();
    expect(preset?.route).toBe("/trends");
    expect(preset?.settledPath).toBe("/trends");
  });

  it("derives on-target, off-target, no-target and no-data days for the requested window", async () => {
    activateVisualReviewPreset("trends.adherence_mix", null);
    const mockFetch = createE2EMockFetch();
    const summaries = await getDailySummaryRange(apiSession, from, to, mockFetch);

    const dates = summaries.map((s) => s.date);
    expect(dates[0]).toBe(from);
    expect(dates[dates.length - 1]).toBe(to);

    const { days } = computeAdherence(summaries, dates);
    expect(new Set(days.map((d) => d.state))).toEqual(
      new Set(["on-target", "off-target", "no-target", "no-data"]),
    );

    // The strip scrolls to its newest end, so the framed cells are the tail —
    // all four states must appear there, not only deep in the scrolled-off past.
    const framed = days.slice(-8).map((d) => d.state);
    expect(new Set(framed)).toEqual(
      new Set(["on-target", "off-target", "no-target", "no-data"]),
    );
  });

  it("is inert until activated: another preset keeps the default range fixture", async () => {
    activateVisualReviewPreset("trends.populated", null);
    const mockFetch = createE2EMockFetch();
    const summaries = await getDailySummaryRange(apiSession, from, to, mockFetch);
    const { days } = computeAdherence(
      summaries,
      summaries.map((s) => s.date),
    );
    // The default fixture never produces a no-target day — that gap is exactly
    // why this preset exists.
    expect(days.some((d) => d.state === "no-target")).toBe(false);
  });
});
