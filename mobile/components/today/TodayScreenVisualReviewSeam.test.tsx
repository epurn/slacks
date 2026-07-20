import { act } from "react-test-renderer";

import { TodayScreen } from "@/components/TodayScreen";
import {
  __deactivateVisualReview,
  getVisualReviewCore,
  resolveVisualReviewFetch,
} from "@/e2e/visualReview/session";
import {
  E2E_PRIOR_CORRECTION_CANDIDATE,
  E2E_SOURCE_CANDIDATE,
} from "@/e2e/fixtures";
import { activateVisualReviewPreset } from "@/e2e/visualReview";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

import {
  INACTIVE,
  SESSION,
  cleanupTrees,
  hasA11yLabel,
  inputValue,
  mount,
} from "./todayTestUtils";

/**
 * FTY-263: the correction sheet's `detail` / `typeahead` / `confirm_apply`
 * sub-states are component-local state with no route param or tap-free entry
 * point. This suite proves the E2E-only visual-review seam
 * (`components/correction/visualReviewSeam.ts`) reaches all three directly —
 * never via a scripted tap on a rendered row — and that the seam is inert
 * outside `isE2EMode()`, independent of FTY-247's own route-level gate.
 *
 * Importing `TodayScreen` pulls in `useTodayData` → `visualReviewSeam`, whose
 * module-load side effect registers the `correction.*` presets, so no
 * additional registration import is needed here.
 */

jest.mock("@/theme/haptics", () => ({
  entryResolvedHaptic: jest.fn(),
  correctionSavedHaptic: jest.fn(),
  targetReachedHaptic: jest.fn(),
}));

// The item-forward by-date feed is read from a real endpoint by default
// (FTY-180); stub it to empty so these tests stay hermetic. The seam never
// relies on this feed — it opens the sheet directly over a synthetic item.
jest.mock("@/api/logEvents", () => {
  const actual = jest.requireActual("@/api/logEvents");
  return {
    ...actual,
    listTodayLogEventEntries: jest.fn().mockResolvedValue([]),
  };
});

const gThis = globalThis as Record<string, unknown>;
const ORIGINAL_DEV = gThis["__DEV__"] as boolean;
const ORIGINAL_E2E_ENV = process.env.EXPO_PUBLIC_SLACKS_E2E;

function setE2E(on: boolean): void {
  gThis["__DEV__"] = on;
  if (on) {
    process.env["EXPO_PUBLIC_SLACKS_E2E"] = "true";
  } else {
    delete process.env["EXPO_PUBLIC_SLACKS_E2E"];
  }
}

beforeEach(() => mockReduceMotion(false));

afterEach(() => {
  cleanupTrees();
  __deactivateVisualReview();
  gThis["__DEV__"] = ORIGINAL_DEV;
  if (ORIGINAL_E2E_ENV === undefined) {
    delete process.env["EXPO_PUBLIC_SLACKS_E2E"];
  } else {
    process.env["EXPO_PUBLIC_SLACKS_E2E"] = ORIGINAL_E2E_ENV;
  }
});

describe("Correction sheet visual-review seam (FTY-263)", () => {
  it("opens correction.detail directly in the quick-fix mode — no tap on any row", async () => {
    setE2E(true);
    activateVisualReviewPreset("correction.detail", null);
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    expect(hasA11yLabel(tree, "Increase amount")).toBe(true);
    expect(hasA11yLabel(tree, "Decrease amount")).toBe(true);
    // The settled marker is rendered inside the correction sheet's modal subtree
    // once the sheet + synthetic item have rendered (FTY-263) — the marker
    // screenshot automation waits on, reachable while the sheet is presented.
    expect(hasA11yLabel(tree, "visual-review-settled:correction.detail")).toBe(true);
  });

  it("opens correction.typeahead directly in change-match mode with candidates already loaded — no tap", async () => {
    setE2E(true);
    activateVisualReviewPreset("correction.typeahead", null);
    const listSourceCandidates = jest.fn().mockResolvedValue({
      candidates: [
        {
          source_type: "trusted_nutrition_database",
          source_ref: "usda_fdc:171477",
          name: "Chicken, grilled, USDA",
          basis: "per_100g",
          calories: 165,
          protein_g: 31,
          carbs_g: 0,
          fat_g: 3.6,
        },
      ],
      priorCorrections: [],
    });
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        listSourceCandidates={listSourceCandidates}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // The change-match panel is open (not the "Change match" lever button),
    // with the candidate list already loaded — never a blank/empty panel.
    expect(hasA11yLabel(tree, "Cancel change match")).toBe(true);
    expect(listSourceCandidates).toHaveBeenCalled();
    expect(
      hasA11yLabel(tree, "Select Chicken, grilled, USDA, 165 kcal per 100g"),
    ).toBe(true);
    // The in-modal settled marker appears only once candidatesLoading === false
    // with the candidate list painted — the expanded, dimmed-detent case that
    // failed on PR #230, now reachable from inside the sheet's modal subtree.
    expect(hasA11yLabel(tree, "visual-review-settled:correction.typeahead")).toBe(true);
  });

  // FTY-407: registration entry for the story's mandated `correction.prior_correction`
  // preset — the change-match panel for an item the user has corrected before.
  // The pair below is the load-bearing part: this preset seeds its OWN
  // `prior_corrections` response, and `correction.typeahead` seeds none, so the
  // history surface is reachable without changing what the shared preset renders.
  describe("correction.prior_correction (FTY-407)", () => {
    const sourceCandidatesCtx = {
      url: "http://localhost:8000/users/u1/derived-items/food/food-1/source-candidates",
      method: "POST",
      pathEnd: "/users/u1/derived-items/food/food-1/source-candidates",
    };

    it("seeds a prior correction alongside the guessed candidate", async () => {
      setE2E(true);
      activateVisualReviewPreset("correction.prior_correction", null);
      const seeded = resolveVisualReviewFetch(sourceCandidatesCtx);
      expect(seeded).not.toBeNull();
      const body = (await seeded!.json()) as {
        candidates: { name: string }[];
        prior_corrections: { source_ref: string; basis: string; fat_g: number | null }[];
      };
      expect(body.candidates).toHaveLength(1);
      expect(body.prior_corrections).toHaveLength(1);
      expect(body.prior_corrections[0]?.source_ref).toBe(
        E2E_PRIOR_CORRECTION_CANDIDATE.source_ref,
      );
      // as_logged total for this item's own portion, not a per-100g density.
      expect(body.prior_corrections[0]?.basis).toBe("as_logged");
      // A macro the correction never supplied stays honestly unknown.
      expect(body.prior_corrections[0]?.fat_g).toBeNull();
    });

    it("leaves correction.typeahead's candidate response untouched", () => {
      setE2E(true);
      activateVisualReviewPreset("correction.typeahead", null);
      // No source-candidates override at all: `typeahead` falls through to the
      // shared E2E mock, which offers no history — byte-for-byte what it
      // rendered before FTY-407.
      expect(resolveVisualReviewFetch(sourceCandidatesCtx)).toBeNull();
    });

    it("opens directly in change-match mode with the prior correction ranked above the guess", async () => {
      setE2E(true);
      activateVisualReviewPreset("correction.prior_correction", null);
      const listSourceCandidates = jest.fn().mockResolvedValue({
        candidates: [E2E_SOURCE_CANDIDATE],
        priorCorrections: [E2E_PRIOR_CORRECTION_CANDIDATE],
      });
      const load = jest.fn().mockResolvedValue([]);
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          listSourceCandidates={listSourceCandidates}
          useActive={INACTIVE}
        />,
      );
      await act(async () => {});

      expect(hasA11yLabel(tree, "Cancel change match")).toBe(true);
      expect(
        hasA11yLabel(
          tree,
          `Select ${E2E_PRIOR_CORRECTION_CANDIDATE.name}, your correction, 105 kcal`,
        ),
      ).toBe(true);
      expect(
        hasA11yLabel(tree, `Select ${E2E_SOURCE_CANDIDATE.name}, 165 kcal per 100g`),
      ).toBe(true);
      // The in-modal settled marker the Maestro flow waits on before shooting.
      expect(
        hasA11yLabel(tree, "visual-review-settled:correction.prior_correction"),
      ).toBe(true);
    });
  });

  it("opens correction.confirm_apply directly in override mode with the current value pre-filled — no tap", async () => {
    setE2E(true);
    activateVisualReviewPreset("correction.confirm_apply", null);
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    expect(hasA11yLabel(tree, "Calories value")).toBe(true);
    // Pre-filled with the synthetic oatmeal entry's current calories (140) —
    // "ready to confirm/apply", not a blank input the user must fill first.
    expect(inputValue(tree, "Calories value")).toBe("140");
    // The in-modal settled marker appears only once the override panel is up
    // with its pre-seeded draft — reachable inside the sheet's modal subtree.
    expect(hasA11yLabel(tree, "visual-review-settled:correction.confirm_apply")).toBe(true);
  });

  it("is inert outside E2E mode: no sheet auto-opens even with a preset forced active", async () => {
    setE2E(false);
    // Force the core active directly (bypassing the isE2EMode()-gated deep-link
    // route) to prove the seam's OWN gate, not just the route's.
    activateVisualReviewPreset("correction.detail", null);
    expect(getVisualReviewCore().presetName).toBe("correction.detail");

    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    expect(hasA11yLabel(tree, "Increase amount")).toBe(false);
    expect(hasA11yLabel(tree, "Calories value")).toBe(false);
    // No sheet, so no in-modal marker either — the seam is fully inert.
    expect(hasA11yLabel(tree, "visual-review-settled:correction.detail")).toBe(false);
  });

  it("leaves default correction behaviour unchanged when no preset is active", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    expect(hasA11yLabel(tree, "Increase amount")).toBe(false);
    expect(hasA11yLabel(tree, "Calories value")).toBe(false);
  });
});
