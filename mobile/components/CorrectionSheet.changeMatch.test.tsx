/**
 * FTY-093 / FTY-407: the CorrectionSheet "Change match" sub-flow.
 *
 * Covers loading and searching source candidates (debounce + stale-response
 * ordering), applying a chosen match through re-resolve, the detent growth, and
 * the FTY-407 prior-correction candidates that surface the user's own earlier
 * corrections above the guessed matches. Split out of `CorrectionSheet.test.tsx`
 * (FTY-415); shared fixtures/helpers live in `@/testUtils/correctionSheet`.
 */

import { act } from "react-test-renderer";

import { CorrectionSheet } from "./CorrectionSheet";
import { CorrectionsApiError, type SourceCandidates } from "@/api/corrections";
import { cleanupReactTestRenderers } from "@/testUtils/reactTestRenderer";
import { sourceCandidates } from "@/testUtils/correctionCandidates";
import { mockReduceMotion } from "@/testUtils/reduceMotion";
import {
  SESSION,
  allText,
  candidate,
  defaultProps,
  food,
  hasA11yLabel,
  mount,
  priorCorrection,
  pressAsync,
  typeInto,
} from "@/testUtils/correctionSheet";

jest.mock("@/theme/haptics", () => ({
  correctionSavedHaptic: jest.fn(),
  entryResolvedHaptic: jest.fn(),
  targetReachedHaptic: jest.fn(),
}));

// expo-symbols is a native module — replace SymbolView with a View stub that
// exposes the symbol name via testID (same pattern as AppIcon.test.tsx); the
// provenance block renders its SF Symbol through it.
jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require("react");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require("react-native");
  return {
    SymbolView: ({
      name,
      accessibilityLabel,
    }: {
      name: string;
      tintColor?: string;
      size?: number;
      accessibilityLabel?: string;
    }) =>
      React.createElement(View, {
        testID: `sf-symbol-${String(name)}`,
        accessibilityLabel,
      }),
  };
});

beforeEach(() => {
  mockReduceMotion(false);
});

afterEach(() => {
  cleanupReactTestRenderers();
  jest.restoreAllMocks();
});

// ─── Change-match flow (FTY-093) ───────────────────────────────────────────────

describe("change-match flow", () => {
  it("shows 'Change match' lever", () => {
    const tree = mount(<CorrectionSheet {...defaultProps()} />);
    expect(hasA11yLabel(tree, "Change match")).toBe(true);
  });

  it("loads candidates and shows them when Change match is tapped", async () => {
    const listCandidates = jest.fn().mockResolvedValue(
      sourceCandidates([
        candidate({ name: "Turkey breast, roasted" }),
        candidate({ name: "Turkey breast, raw", source_ref: "usda_fdc:888" }),
      ]),
    );
    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
    await pressAsync(tree, "Change match");
    expect(listCandidates).toHaveBeenCalledWith(SESSION, "food-1", undefined);
    expect(allText(tree)).toContain("Turkey breast, roasted");
  });

  it("debounces keystrokes into a single search request for the final query", async () => {
    jest.useFakeTimers();
    try {
      const listCandidates = jest.fn().mockResolvedValue(sourceCandidates());
      const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
      await pressAsync(tree, "Change match"); // immediate initial load
      listCandidates.mockClear();

      typeInto(tree, "Search for a food", "c");
      typeInto(tree, "Search for a food", "ch");
      typeInto(tree, "Search for a food", "chicken");
      // Within the debounce window no request has fired yet — no per-keystroke fan-out.
      expect(listCandidates).not.toHaveBeenCalled();

      await act(async () => {
        jest.advanceTimersByTime(300);
      });
      expect(listCandidates).toHaveBeenCalledTimes(1);
      expect(listCandidates).toHaveBeenCalledWith(SESSION, "food-1", "chicken");
    } finally {
      jest.useRealTimers();
    }
  });

  it("ignores a stale earlier response that resolves after a newer query", async () => {
    jest.useFakeTimers();
    try {
      const listCandidates = jest.fn().mockResolvedValue(sourceCandidates());
      const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
      await pressAsync(tree, "Change match"); // initial load resolves []

      // The first typed query ("a") hangs; the second ("ab") resolves immediately.
      let resolveStale: ((v: SourceCandidates) => void) | undefined;
      listCandidates.mockImplementationOnce(
        () => new Promise((resolve) => { resolveStale = resolve; }),
      );
      listCandidates.mockImplementationOnce(() =>
        Promise.resolve(
          sourceCandidates([candidate({ name: "Fresh match", source_ref: "usda_fdc:fresh" })]),
        ),
      );

      typeInto(tree, "Search for a food", "a");
      await act(async () => { jest.advanceTimersByTime(300); }); // fires "a" (pending)
      typeInto(tree, "Search for a food", "ab");
      await act(async () => { jest.advanceTimersByTime(300); }); // fires "ab" → Fresh match

      expect(allText(tree)).toContain("Fresh match");

      // The slower "a" response lands last; the ordering guard must discard it.
      await act(async () => {
        resolveStale?.(
          sourceCandidates([candidate({ name: "Stale match", source_ref: "usda_fdc:stale" })]),
        );
      });
      expect(allText(tree)).toContain("Fresh match");
      expect(allText(tree)).not.toContain("Stale match");
    } finally {
      jest.useRealTimers();
    }
  });

  it("calls reResolve with the chosen source_ref", async () => {
    const c = candidate({ source_ref: "usda_fdc:999" });
    const listCandidates = jest.fn().mockResolvedValue(sourceCandidates([c]));
    const updatedFood = food({ source: { source_type: "trusted_nutrition_database", label: "USDA", ref: "usda_fdc:999" } });
    const reResolve = jest.fn().mockResolvedValue(updatedFood);
    const onItemChange = jest.fn();

    const tree = mount(
      <CorrectionSheet {...defaultProps({ listCandidates, reResolve, onItemChange })} />,
    );
    await pressAsync(tree, "Change match");
    await pressAsync(tree, "Select Turkey breast, roasted, 135 kcal per 100g");

    expect(reResolve).toHaveBeenCalledWith(SESSION, "food-1", "usda_fdc:999");
    expect(onItemChange).toHaveBeenCalledWith(updatedFood);
  });

  it("returns to normal mode and shows updated provenance after a successful re-resolve", async () => {
    const c = candidate();
    const listCandidates = jest.fn().mockResolvedValue(sourceCandidates([c]));
    const reResolve = jest.fn().mockResolvedValue(food({ name: "Turkey breast, roasted" }));

    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates, reResolve })} />);
    await pressAsync(tree, "Change match");
    await pressAsync(tree, "Select Turkey breast, roasted, 135 kcal per 100g");

    // Should be back in normal mode: Change match button visible again, not the candidate list
    expect(hasA11yLabel(tree, "Change match")).toBe(true);
    expect(hasA11yLabel(tree, "Cancel change match")).toBe(false);
  });

  it("shows a retryable error when re-resolve fails", async () => {
    const c = candidate();
    const listCandidates = jest.fn().mockResolvedValue(sourceCandidates([c]));
    // The FTY-366 per-flow copy the real client maps for a re-resolve 422.
    const reResolve = jest.fn().mockRejectedValue(
      new CorrectionsApiError(
        422,
        "That match couldn't be applied. Pick a different match or search again.",
      ),
    );

    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates, reResolve })} />);
    await pressAsync(tree, "Change match");
    await pressAsync(tree, "Select Turkey breast, roasted, 135 kcal per 100g");

    expect(allText(tree)).toContain("couldn't be applied");
    expect(hasA11yLabel(tree, "Cancel change match")).toBe(true);
  });

  // ─── FTY-407: prior corrections as match candidates ─────────────────────────
  //
  // The operator's dogfood case: a food the user has already hand-corrected
  // ("black coffee") is re-guessed wrong on the next log. Their own corrected
  // value is offered as a top-ranked candidate, and picking it applies through
  // the same FTY-411 re-resolve path.

  it("surfaces the user's prior correction as a pickable candidate above the guessed matches", async () => {
    const listCandidates = jest
      .fn()
      .mockResolvedValue(sourceCandidates([candidate()], [priorCorrection()]));
    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
    await pressAsync(tree, "Change match");

    const text = allText(tree);
    expect(text).toContain("Your corrections");
    // The corrected total for this portion, with its provenance — never the
    // guessed source's "/ 100g" density copy.
    expect(text).toContain("3 kcal · Your correction");
    expect(hasA11yLabel(tree, "Select Black coffee, your correction, 3 kcal")).toBe(true);
    // The guessed match is still offered, under its own header.
    expect(text).toContain("Other matches");
    expect(hasA11yLabel(tree, "Select Turkey breast, roasted, 135 kcal per 100g")).toBe(true);
  });

  it("applies the corrected values when the prior correction is picked", async () => {
    const corrected = food({
      name: "Black coffee",
      calories: 3,
      source: {
        source_type: "prior_correction",
        label: "Your correction",
        ref: "prior_correction:abc123",
      },
    });
    const listCandidates = jest
      .fn()
      .mockResolvedValue(sourceCandidates([candidate()], [priorCorrection()]));
    const reResolve = jest.fn().mockResolvedValue(corrected);
    const onItemChange = jest.fn();

    const tree = mount(
      <CorrectionSheet {...defaultProps({ listCandidates, reResolve, onItemChange })} />,
    );
    await pressAsync(tree, "Change match");
    await pressAsync(tree, "Select Black coffee, your correction, 3 kcal");

    // Applied through FTY-411's apply path — the opaque prior_correction ref,
    // never client-supplied nutrition values.
    expect(reResolve).toHaveBeenCalledWith(SESSION, "food-1", "prior_correction:abc123");
    expect(onItemChange).toHaveBeenCalledWith(corrected);
    // The flow completes: back to the normal sheet, showing the corrected value
    // with its "Your correction" provenance.
    expect(hasA11yLabel(tree, "Change match")).toBe(true);
    expect(hasA11yLabel(tree, "Cancel change match")).toBe(false);
    expect(allText(tree)).toContain("Your correction");
  });

  it("renders a rescaled prior correction as adjusted for this amount", async () => {
    const listCandidates = jest
      .fn()
      .mockResolvedValue(
        sourceCandidates([], [priorCorrection({ calories: 6, rescaled: true })]),
      );
    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
    await pressAsync(tree, "Change match");

    expect(allText(tree)).toContain("6 kcal · Your correction, adjusted for this amount");
    expect(
      hasA11yLabel(
        tree,
        "Select Black coffee, your correction, 6 kcal, adjusted for this amount",
      ),
    ).toBe(true);
  });

  it("offers a prior correction even when no guessed candidate matches", async () => {
    const listCandidates = jest
      .fn()
      .mockResolvedValue(sourceCandidates([], [priorCorrection()]));
    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
    await pressAsync(tree, "Change match");

    // Not the empty state — the user's own history is a usable match.
    expect(allText(tree)).not.toContain("No alternatives available");
    expect(hasA11yLabel(tree, "Select Black coffee, your correction, 3 kcal")).toBe(true);
    // With nothing to separate it from, the guessed-source header is absent.
    expect(allText(tree)).not.toContain("Other matches");
  });

  it("leaves the candidate list unchanged when there is no matching history", async () => {
    const listCandidates = jest
      .fn()
      .mockResolvedValue(sourceCandidates([candidate()], []));
    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
    await pressAsync(tree, "Change match");

    const text = allText(tree);
    // No history ⇒ no section headers at all, exactly as before FTY-407.
    expect(text).not.toContain("Your corrections");
    expect(text).not.toContain("Other matches");
    expect(text).not.toContain("Your correction");
    expect(hasA11yLabel(tree, "Select Turkey breast, roasted, 135 kcal per 100g")).toBe(true);
  });

  it("shows an error when the candidates source is unavailable (503)", async () => {
    const listCandidates = jest.fn().mockRejectedValue(
      new CorrectionsApiError(503, "Alternatives are temporarily unavailable. Try again in a moment."),
    );
    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
    await pressAsync(tree, "Change match");
    expect(allText(tree)).toContain("temporarily unavailable");
  });

  it("shows empty state when no candidates exist", async () => {
    const listCandidates = jest.fn().mockResolvedValue(sourceCandidates());
    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
    await pressAsync(tree, "Change match");
    expect(allText(tree)).toContain("No alternatives available");
  });

  it("opening Change match grows to large detent (expanded)", async () => {
    const listCandidates = jest.fn().mockResolvedValue(sourceCandidates());
    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
    await pressAsync(tree, "Change match");
    // In large mode the sheetLarge style is applied (maxHeight 90%) — verify
    // by checking that the cancel button is now visible (only in change-match mode).
    expect(hasA11yLabel(tree, "Cancel change match")).toBe(true);
  });

  // The `Make it exact` nudge now opens the dedicated exact-evidence choice
  // surface (barcode/label), not Change match — see CorrectionSheet.exact.test.tsx.
});
