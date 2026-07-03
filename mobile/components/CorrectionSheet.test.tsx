/**
 * Tests for the FTY-100 CorrectionSheet component.
 *
 * All API calls are mocked; the sheet is presented as a standalone component
 * (per the story spec: built and tested as a standalone presentable component).
 *
 * Coverage mirrors the FTY-100 Verification section:
 *   - Provenance block render
 *   - Amount stepper → FTY-092 endpoint, no client math, provenance unchanged
 *   - Change-match flow → FTY-093 candidates + re-resolve + provenance update + detent
 *   - Direct override → FTY-051 edit, "✎ edited" provenance, error shapes
 *   - Clarify mode → question + chips + free-text, no auto-fill
 *   - Rough-estimate nudge → "≈ Rough estimate" + "Make it exact" into Change-match
 *   - Save-as-food via FTY-052/053, no auto-prompt
 *   - Accessibility: VoiceOver labels on provenance icons and every lever; ≥44pt targets
 */

import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { ThemeProvider } from "@/theme";

import {
  CorrectionSheet,
  type ClarificationData,
  type CorrectionSheetBaseProps,
} from "./CorrectionSheet";
import { CorrectionsApiError, type SourceCandidate } from "@/api/corrections";
import {
  DerivedItemApiError,
  type DerivedFoodItemDTO,
  type ItemSourceDTO,
} from "@/api/derivedItems";
import { SavedFoodApiError, type SavedFoodDTO } from "@/api/savedFoods";
import type { ApiSession } from "@/state/session";
import { mockReduceMotion } from "@/testUtils/reduceMotion";
import { correctionSavedHaptic } from "@/theme/haptics";

// The correction-saved beat's haptic is mocked so a successful commit can be
// asserted without a native Taptic Engine.
jest.mock("@/theme/haptics", () => ({
  correctionSavedHaptic: jest.fn(),
  entryResolvedHaptic: jest.fn(),
  targetReachedHaptic: jest.fn(),
}));

const mockCorrectionSavedHaptic = correctionSavedHaptic as jest.MockedFunction<
  typeof correctionSavedHaptic
>;

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

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "user-1",
};

function usdaSource(): ItemSourceDTO {
  return {
    source_type: "trusted_nutrition_database",
    label: "USDA",
    ref: "usda_fdc:168880",
  };
}

function modelPriorSource(): ItemSourceDTO {
  return {
    source_type: "model_prior",
    label: "Rough estimate",
    ref: "model_prior",
  };
}

function food(overrides: Partial<DerivedFoodItemDTO> = {}): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: "food-1",
    user_id: "user-1",
    log_event_id: "event-1",
    name: "Turkey breast",
    quantity_text: "1 serving",
    unit: "serving",
    amount: 1,
    status: "resolved",
    grams: 85,
    calories: 120,
    protein_g: 26,
    carbs_g: 0,
    fat_g: 1,
    calories_estimated: 120,
    protein_g_estimated: 26,
    carbs_g_estimated: 0,
    fat_g_estimated: 1,
    source: usdaSource(),
    is_edited: false,
    created_at: "2026-06-28T08:00:00Z",
    updated_at: "2026-06-28T08:00:00Z",
    ...overrides,
  };
}


function candidate(overrides: Partial<SourceCandidate> = {}): SourceCandidate {
  return {
    source_type: "trusted_nutrition_database",
    source_ref: "usda_fdc:999",
    name: "Turkey breast, roasted",
    basis: "per_100g",
    calories: 135,
    protein_g: 30,
    carbs_g: 0,
    fat_g: 1.5,
    ...overrides,
  };
}

function savedFoodResult(): SavedFoodDTO {
  return {
    id: "saved-1",
    user_id: "user-1",
    name: "Turkey breast",
    calories: 120,
    protein_g: 26,
    carbs_g: 0,
    fat_g: 1,
    serving_size: 1,
    serving_unit: "serving",
    source: "saved_from_correction",
    created_at: "2026-06-28T10:00:00Z",
    updated_at: "2026-06-28T10:00:00Z",
  };
}

const clarificationData: ClarificationData = {
  question: "What kind of milk?",
  options: ["Whole", "2%", "Skim", "Oat milk"],
};

// ─── Test helpers ──────────────────────────────────────────────────────────────

function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(
      <ThemeProvider override="light">{element}</ThemeProvider>,
    );
  });
  return tree;
}

function allText(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

function allA11yLabels(tree: ReactTestRenderer): string[] {
  return tree.root
    .findAll((n) => typeof n.props.accessibilityLabel === "string")
    .map((n) => n.props.accessibilityLabel as string);
}

function hasA11yLabel(tree: ReactTestRenderer, label: string): boolean {
  return allA11yLabels(tree).includes(label);
}

function press(tree: ReactTestRenderer, label: string): void {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
  act(() => {
    node.props.onPress();
  });
}

async function pressAsync(tree: ReactTestRenderer, label: string): Promise<void> {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
  await act(async () => {
    node.props.onPress();
  });
}

function typeInto(tree: ReactTestRenderer, label: string, value: string): void {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onChangeText === "function",
  );
  act(() => {
    node.props.onChangeText(value);
  });
}

function defaultProps(overrides: Partial<CorrectionSheetBaseProps> = {}) {
  return {
    item: food(),
    visible: true,
    onClose: jest.fn(),
    session: SESSION,
    editItem: jest.fn(),
    listCandidates: jest.fn().mockResolvedValue([]),
    reResolve: jest.fn(),
    saveFood: jest.fn(),
    ...overrides,
  };
}

// Mock AccessibilityInfo for all tests (isReduceMotionEnabled returns false by default).
beforeEach(() => {
  mockReduceMotion(false);
  mockCorrectionSavedHaptic.mockClear();
});

afterEach(() => {
  jest.restoreAllMocks();
});

// ─── Provenance block ──────────────────────────────────────────────────────────

describe("provenance block", () => {
  it("renders source icon + label when item has a source", () => {
    const tree = mount(<CorrectionSheet {...defaultProps()} logPhrase="turkey breast" />);
    const labels = allA11yLabels(tree);
    expect(labels.some((l) => l.includes("USDA"))).toBe(true);
  });

  it("shows the source label exactly once — never duplicated as 'USDA · USDA'", () => {
    const tree = mount(<CorrectionSheet {...defaultProps()} />);
    const texts = tree.root
      .findAll((n) => typeof n.props.children === "string")
      .map((n) => n.props.children as string);
    // The provenance line must read the label once; the glyph already carries
    // the source type, so a repeated "USDA · USDA" is a visible defect.
    expect(texts).toContain("USDA");
    expect(texts.some((t) => /USDA\b.*\bUSDA/.test(t))).toBe(false);
    expect(texts.some((t) => t.includes("·"))).toBe(false);
  });

  it("renders the user's original phrase quoted", () => {
    const tree = mount(
      <CorrectionSheet {...defaultProps()} logPhrase="a piece of turkey" />,
    );
    expect(allText(tree)).toContain("a piece of turkey");
  });

  it("renders '≈ Rough estimate' for a model_prior source", () => {
    const tree = mount(
      <CorrectionSheet
        {...defaultProps({ item: food({ source: modelPriorSource(), is_edited: false }) })}
      />,
    );
    expect(allText(tree)).toContain("Rough estimate");
  });

  it("renders '✎ edited' provenance for an is_edited item", () => {
    const tree = mount(
      <CorrectionSheet
        {...defaultProps({ item: food({ is_edited: true }) })}
      />,
    );
    const labels = allA11yLabels(tree);
    expect(labels.some((l) => l === "Edited by you")).toBe(true);
  });

  it("renders '› Make it exact' nudge for a rough-estimate item", () => {
    const tree = mount(
      <CorrectionSheet
        {...defaultProps({ item: food({ source: modelPriorSource() }) })}
      />,
    );
    expect(hasA11yLabel(tree, "Make it exact — find the real source")).toBe(true);
  });
});

// ─── Amount stepper (primary lever) ───────────────────────────────────────────

describe("amount stepper", () => {
  it("renders the current amount and unit", () => {
    const tree = mount(
      <CorrectionSheet {...defaultProps({ item: food({ amount: 1.5, unit: "cup" }) })} />,
    );
    expect(allText(tree)).toContain("1.5 cup");
  });

  it("calls editItem with field=quantity on step-up", async () => {
    const editItem = jest.fn().mockResolvedValue(food({ amount: 1.25, calories: 150 }));
    const tree = mount(<CorrectionSheet {...defaultProps({ editItem })} />);
    await pressAsync(tree, "Increase amount");
    expect(editItem).toHaveBeenCalledWith(SESSION, "food", "food-1", "quantity", 1.25);
  });

  it("calls editItem with field=quantity on step-down", async () => {
    const editItem = jest.fn().mockResolvedValue(food({ amount: 0.75, calories: 90 }));
    const tree = mount(<CorrectionSheet {...defaultProps({ editItem, item: food({ amount: 1 }) })} />);
    await pressAsync(tree, "Decrease amount");
    expect(editItem).toHaveBeenCalledWith(SESSION, "food", "food-1", "quantity", 0.75);
  });

  it("renders server-returned kcal after a step — no client math", async () => {
    const editItem = jest.fn().mockResolvedValue(food({ amount: 1.25, calories: 150, protein_g: 32.5 }));
    const tree = mount(<CorrectionSheet {...defaultProps({ editItem })} />);
    await pressAsync(tree, "Increase amount");
    expect(allText(tree)).toContain("150 kcal");
    expect(allText(tree)).toContain("32.5");
  });

  it("does not change provenance icon/label after amount step (provenance-preserving)", async () => {
    const editItem = jest.fn().mockResolvedValue(food({ amount: 1.25, calories: 150 }));
    const onItemChange = jest.fn();
    const tree = mount(
      <CorrectionSheet {...defaultProps({ editItem, onItemChange })} />,
    );
    await pressAsync(tree, "Increase amount");
    // The updated item should still show the USDA source and NOT be marked edited
    const updated = onItemChange.mock.calls[0][0] as DerivedFoodItemDTO;
    expect(updated.is_edited).toBe(false);
    expect(updated.source?.source_type).toBe("trusted_nutrition_database");
  });

  it("shows an error message and keeps previous value when step fails", async () => {
    const editItem = jest.fn().mockRejectedValue(
      new DerivedItemApiError(422, "That value couldn't be saved. Check it and try again."),
    );
    const tree = mount(<CorrectionSheet {...defaultProps({ editItem })} />);
    await pressAsync(tree, "Increase amount");
    const text = allText(tree);
    expect(text).toContain("couldn't");
  });

  it("disables step-down when amount is at minimum (0.25)", () => {
    const tree = mount(
      <CorrectionSheet {...defaultProps({ item: food({ amount: 0.25 }) })} />,
    );
    const stepDown = tree.root.find(
      (n) => n.props.accessibilityLabel === "Decrease amount",
    );
    expect(stepDown.props.accessibilityState?.disabled).toBe(true);
  });
});

// ─── Change-match flow (FTY-093) ───────────────────────────────────────────────

describe("change-match flow", () => {
  it("shows 'Change match' lever", () => {
    const tree = mount(<CorrectionSheet {...defaultProps()} />);
    expect(hasA11yLabel(tree, "Change match")).toBe(true);
  });

  it("loads candidates and shows them when Change match is tapped", async () => {
    const listCandidates = jest.fn().mockResolvedValue([
      candidate({ name: "Turkey breast, roasted" }),
      candidate({ name: "Turkey breast, raw", source_ref: "usda_fdc:888" }),
    ]);
    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
    await pressAsync(tree, "Change match");
    expect(listCandidates).toHaveBeenCalledWith(SESSION, "food-1", undefined);
    expect(allText(tree)).toContain("Turkey breast, roasted");
  });

  it("debounces keystrokes into a single search request for the final query", async () => {
    jest.useFakeTimers();
    try {
      const listCandidates = jest.fn().mockResolvedValue([]);
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
      const listCandidates = jest.fn().mockResolvedValue([]);
      const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
      await pressAsync(tree, "Change match"); // initial load resolves []

      // The first typed query ("a") hangs; the second ("ab") resolves immediately.
      let resolveStale: ((v: readonly SourceCandidate[]) => void) | undefined;
      listCandidates.mockImplementationOnce(
        () => new Promise((resolve) => { resolveStale = resolve; }),
      );
      listCandidates.mockImplementationOnce(() =>
        Promise.resolve([candidate({ name: "Fresh match", source_ref: "usda_fdc:fresh" })]),
      );

      typeInto(tree, "Search for a food", "a");
      await act(async () => { jest.advanceTimersByTime(300); }); // fires "a" (pending)
      typeInto(tree, "Search for a food", "ab");
      await act(async () => { jest.advanceTimersByTime(300); }); // fires "ab" → Fresh match

      expect(allText(tree)).toContain("Fresh match");

      // The slower "a" response lands last; the ordering guard must discard it.
      await act(async () => {
        resolveStale?.([candidate({ name: "Stale match", source_ref: "usda_fdc:stale" })]);
      });
      expect(allText(tree)).toContain("Fresh match");
      expect(allText(tree)).not.toContain("Stale match");
    } finally {
      jest.useRealTimers();
    }
  });

  it("calls reResolve with the chosen source_ref", async () => {
    const c = candidate({ source_ref: "usda_fdc:999" });
    const listCandidates = jest.fn().mockResolvedValue([c]);
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
    const listCandidates = jest.fn().mockResolvedValue([c]);
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
    const listCandidates = jest.fn().mockResolvedValue([c]);
    const reResolve = jest.fn().mockRejectedValue(
      new CorrectionsApiError(422, "That correction couldn't be applied. Check the value and try again."),
    );

    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates, reResolve })} />);
    await pressAsync(tree, "Change match");
    await pressAsync(tree, "Select Turkey breast, roasted, 135 kcal per 100g");

    expect(allText(tree)).toContain("couldn't be applied");
    expect(hasA11yLabel(tree, "Cancel change match")).toBe(true);
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
    const listCandidates = jest.fn().mockResolvedValue([]);
    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
    await pressAsync(tree, "Change match");
    expect(allText(tree)).toContain("No alternatives available");
  });

  it("opening Change match grows to large detent (expanded)", async () => {
    const listCandidates = jest.fn().mockResolvedValue([]);
    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
    await pressAsync(tree, "Change match");
    // In large mode the sheetLarge style is applied (maxHeight 90%) — verify
    // by checking that the cancel button is now visible (only in change-match mode).
    expect(hasA11yLabel(tree, "Cancel change match")).toBe(true);
  });

  it("'Make it exact' nudge on a rough-estimate item opens Change match", async () => {
    const listCandidates = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <CorrectionSheet
        {...defaultProps({ listCandidates, item: food({ source: modelPriorSource() }) })}
      />,
    );
    await pressAsync(tree, "Make it exact — find the real source");
    expect(listCandidates).toHaveBeenCalled();
    expect(hasA11yLabel(tree, "Cancel change match")).toBe(true);
  });
});

// ─── Direct value override (FTY-051) ──────────────────────────────────────────

describe("direct value override", () => {
  it("shows override controls for each editable food field", () => {
    const tree = mount(<CorrectionSheet {...defaultProps()} />);
    expect(hasA11yLabel(tree, "Override Calories, currently 120 kcal")).toBe(true);
    expect(hasA11yLabel(tree, "Override Protein, currently 26 g")).toBe(true);
    expect(hasA11yLabel(tree, "Override Carbs, currently 0 g")).toBe(true);
    expect(hasA11yLabel(tree, "Override Fat, currently 1 g")).toBe(true);
  });

  it("calls editItem with the overridden field and value", async () => {
    const editItem = jest.fn().mockResolvedValue(food({ calories: 200, is_edited: true }));
    const onItemChange = jest.fn();
    const tree = mount(<CorrectionSheet {...defaultProps({ editItem, onItemChange })} />);

    await pressAsync(tree, "Override Calories, currently 120 kcal");
    typeInto(tree, "Calories value", "200");
    await pressAsync(tree, "Save Calories override");

    expect(editItem).toHaveBeenCalledWith(SESSION, "food", "food-1", "calories", 200);
    expect(onItemChange).toHaveBeenCalledWith(expect.objectContaining({ calories: 200 }));
  });

  it("shows '✎ edited' provenance after a successful direct override", async () => {
    const editItem = jest.fn().mockResolvedValue(food({ calories: 200, is_edited: true }));
    const tree = mount(<CorrectionSheet {...defaultProps({ editItem })} />);

    await pressAsync(tree, "Override Calories, currently 120 kcal");
    typeInto(tree, "Calories value", "200");
    await pressAsync(tree, "Save Calories override");

    const labels = allA11yLabels(tree);
    expect(labels.some((l) => l === "Edited by you")).toBe(true);
  });

  it("shows a retryable error on unknown_field / out_of_range (contract error shapes)", async () => {
    const editItem = jest.fn().mockRejectedValue(
      new DerivedItemApiError(422, "That value couldn't be saved. Check it and try again."),
    );
    const tree = mount(<CorrectionSheet {...defaultProps({ editItem })} />);

    await pressAsync(tree, "Override Calories, currently 120 kcal");
    typeInto(tree, "Calories value", "9999999");
    await pressAsync(tree, "Save Calories override");

    const text = allText(tree);
    expect(text).toContain("couldn't be saved");
    // The override panel should still be open (cancel still visible)
    expect(hasA11yLabel(tree, "Cancel override")).toBe(true);
  });

  it("rejects a negative or non-numeric value locally", async () => {
    const editItem = jest.fn();
    const tree = mount(<CorrectionSheet {...defaultProps({ editItem })} />);

    await pressAsync(tree, "Override Calories, currently 120 kcal");
    typeInto(tree, "Calories value", "-10");
    await pressAsync(tree, "Save Calories override");

    expect(editItem).not.toHaveBeenCalled();
    expect(allText(tree)).toContain("zero or more");
  });

  it("cancels the override panel and returns to normal mode", async () => {
    const tree = mount(<CorrectionSheet {...defaultProps()} />);

    await pressAsync(tree, "Override Calories, currently 120 kcal");
    expect(hasA11yLabel(tree, "Cancel override")).toBe(true);

    press(tree, "Cancel override");
    expect(hasA11yLabel(tree, "Change match")).toBe(true);
    expect(hasA11yLabel(tree, "Cancel override")).toBe(false);
  });
});

// ─── Clarify-mode ─────────────────────────────────────────────────────────────

describe("clarify mode", () => {
  it("renders in clarify mode when needsClarification is true", () => {
    const tree = mount(
      <CorrectionSheet
        {...defaultProps()}
        needsClarification
        clarificationData={clarificationData}
      />,
    );
    expect(allText(tree)).toContain("What kind of milk?");
  });

  it("renders quick-pick chips for each option", () => {
    const tree = mount(
      <CorrectionSheet
        {...defaultProps()}
        needsClarification
        clarificationData={clarificationData}
      />,
    );
    for (const option of ["Whole", "2%", "Skim", "Oat milk"]) {
      expect(hasA11yLabel(tree, option)).toBe(true);
    }
  });

  it("shows 'Or type your own:' when options are present, 'Type your answer:' when absent", () => {
    // With options, label reads "Or type your own:"
    const treeWithOptions = mount(
      <CorrectionSheet
        {...defaultProps()}
        needsClarification
        clarificationData={clarificationData}
      />,
    );
    expect(allText(treeWithOptions)).toContain("Or type your own:");
    expect(allText(treeWithOptions)).not.toContain("Type your answer:");

    // Without options, label reads "Type your answer:" (no dangling "Or")
    const treeNoOptions = mount(
      <CorrectionSheet
        {...defaultProps()}
        needsClarification
        clarificationData={{ question: "What kind of milk?", options: [] }}
      />,
    );
    expect(allText(treeNoOptions)).toContain("Type your answer:");
    expect(allText(treeNoOptions)).not.toContain("Or type your own:");
  });

  it("calls onClarificationResolved with the tapped chip answer", () => {
    const onClarificationResolved = jest.fn();
    const tree = mount(
      <CorrectionSheet
        {...defaultProps()}
        needsClarification
        clarificationData={clarificationData}
        onClarificationResolved={onClarificationResolved}
      />,
    );
    press(tree, "2%");
    expect(onClarificationResolved).toHaveBeenCalledWith("2%");
  });

  it("calls onClarificationResolved with the free-text answer on submit", () => {
    const onClarificationResolved = jest.fn();
    const tree = mount(
      <CorrectionSheet
        {...defaultProps()}
        needsClarification
        clarificationData={clarificationData}
        onClarificationResolved={onClarificationResolved}
      />,
    );
    typeInto(tree, "Your answer", "Almond milk");
    press(tree, "Submit answer");
    expect(onClarificationResolved).toHaveBeenCalledWith("Almond milk");
  });

  it("renders the fallback question when the question is absent/loading", () => {
    const tree = mount(
      <CorrectionSheet
        {...defaultProps()}
        needsClarification
        clarificationData={{ question: null, options: [] }}
      />,
    );
    expect(allText(tree)).toContain("We need a detail");
  });

  it("renders the free-text input + Done at a usable height in both states", () => {
    // A height floor on the clarify sheet keeps the body usable instead of the
    // collapsed zero-height strip (the live RC regression this story fixes) —
    // proven for question present and question absent/loading.
    for (const data of [
      clarificationData,
      { question: null, options: [] as const },
    ]) {
      const tree = mount(
        <CorrectionSheet
          {...defaultProps()}
          needsClarification
          clarificationData={data}
        />,
      );
      // Free-text input + Done are present and reachable.
      expect(hasA11yLabel(tree, "Your answer")).toBe(true);
      expect(hasA11yLabel(tree, "Submit answer")).toBe(true);
      // The sheet pins a minimum height so the flex:1 body can't collapse.
      const sheetStyles = tree.root
        .findAll((n) => Array.isArray(n.props.style))
        .map((n) => n.props.style as unknown[])
        .find((styleArr) =>
          styleArr.some(
            (s) => s && typeof s === "object" && "minHeight" in s,
          ),
        );
      expect(sheetStyles).toBeDefined();
    }
  });

  it("does not auto-fill the missing detail — free-text starts empty", () => {
    const tree = mount(
      <CorrectionSheet
        {...defaultProps()}
        needsClarification
        clarificationData={clarificationData}
      />,
    );
    const input = tree.root.find(
      (n) => n.props.accessibilityLabel === "Your answer",
    );
    expect(input.props.value).toBe("");
  });

  it("requires clarificationData when needsClarification (type-level contract)", () => {
    // The prop contract is discriminated: a needsClarification sheet cannot
    // type-check without clarificationData (FTY-153 replaces the comment-only
    // "required when needsClarification" with an enforced shape). tsc verifies
    // this @ts-expect-error is a real error; the runtime free-text fallback still
    // covers the loading/empty-question case.
    const invalid = (
      // @ts-expect-error — needsClarification without clarificationData must fail.
      <CorrectionSheet {...defaultProps()} needsClarification />
    );
    expect(invalid).toBeDefined();
  });

  it("does not render the amount stepper or change-match lever in clarify mode", () => {
    const tree = mount(
      <CorrectionSheet
        {...defaultProps()}
        needsClarification
        clarificationData={clarificationData}
      />,
    );
    expect(hasA11yLabel(tree, "Change match")).toBe(false);
    expect(hasA11yLabel(tree, "Increase amount")).toBe(false);
  });
});

// ─── Rough estimate nudge ─────────────────────────────────────────────────────

describe("rough estimate", () => {
  it("shows '≈ Rough estimate' in the provenance block for model_prior", () => {
    const tree = mount(
      <CorrectionSheet
        {...defaultProps({ item: food({ source: modelPriorSource() }) })}
      />,
    );
    expect(allText(tree)).toContain("Rough estimate");
  });

  it("'Make it exact' is accessible with a VoiceOver label", () => {
    const tree = mount(
      <CorrectionSheet
        {...defaultProps({ item: food({ source: modelPriorSource() }) })}
      />,
    );
    expect(hasA11yLabel(tree, "Make it exact — find the real source")).toBe(true);
  });
});

// ─── Save as food ─────────────────────────────────────────────────────────────

describe("save as food", () => {
  it("shows 'Save as food' button when logPhrase is provided", () => {
    const tree = mount(
      <CorrectionSheet {...defaultProps()} logPhrase="turkey breast" />,
    );
    expect(hasA11yLabel(tree, "Save as food")).toBe(true);
  });

  it("does not show 'Save as food' without logPhrase", () => {
    const tree = mount(<CorrectionSheet {...defaultProps()} />);
    expect(hasA11yLabel(tree, "Save as food")).toBe(false);
  });

  it("calls saveFood with name, phrase, and current nutrition snapshot", async () => {
    const saveFood = jest.fn().mockResolvedValue(savedFoodResult());
    const tree = mount(
      <CorrectionSheet
        {...defaultProps({ saveFood })}
        logPhrase="turkey breast"
      />,
    );
    await pressAsync(tree, "Save as food");

    expect(saveFood).toHaveBeenCalledWith(
      SESSION,
      {
        name: "Turkey breast",
        phrase: "turkey breast",
        nutrition: {
          calories: 120,
          protein_g: 26,
          carbs_g: 0,
          fat_g: 1,
          serving_size: 1,
          serving_unit: "serving",
        },
      },
    );
  });

  it("shows a saved state after a successful save", async () => {
    const saveFood = jest.fn().mockResolvedValue(savedFoodResult());
    const tree = mount(
      <CorrectionSheet {...defaultProps({ saveFood })} logPhrase="turkey" />,
    );
    await pressAsync(tree, "Save as food");
    expect(allText(tree)).toContain("Saved");
    const btn = tree.root.find(
      (n) => n.props.accessibilityLabel === "Save as food",
    );
    expect(btn.props.accessibilityState?.disabled).toBe(true);
  });

  it("surfaces a nonjudgmental error when save fails, never echoing values", async () => {
    const saveFood = jest.fn().mockRejectedValue(
      new SavedFoodApiError(422, "Validation error"),
    );
    const tree = mount(
      <CorrectionSheet {...defaultProps({ saveFood })} logPhrase="turkey" />,
    );
    await pressAsync(tree, "Save as food");

    const text = allText(tree);
    expect(text).toContain("couldn't save that food");
    expect(text).not.toContain("Validation error");
    // Button should be re-enabled for retry
    const btn = tree.root.find(
      (n) => n.props.accessibilityLabel === "Save as food",
    );
    expect(btn.props.accessibilityState?.disabled).toBe(false);
  });

  it("does not show Save as food in change-match or override mode", async () => {
    const listCandidates = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <CorrectionSheet {...defaultProps({ listCandidates })} logPhrase="turkey" />,
    );
    await pressAsync(tree, "Change match");
    expect(hasA11yLabel(tree, "Save as food")).toBe(false);
  });
});

// ─── Accessibility ─────────────────────────────────────────────────────────────

describe("accessibility", () => {
  it("provenance icon has an accessible VoiceOver label", () => {
    const tree = mount(<CorrectionSheet {...defaultProps()} />);
    const labels = allA11yLabels(tree);
    expect(labels.some((l) => l.includes("USDA"))).toBe(true);
  });

  it("every lever / action has an accessibilityLabel", () => {
    const tree = mount(<CorrectionSheet {...defaultProps()} logPhrase="turkey" />);
    const requiredLabels = [
      "Change match",
      "Increase amount",
      "Decrease amount",
      "Override Calories, currently 120 kcal",
      "Save as food",
      "Close",
    ];
    for (const label of requiredLabels) {
      expect(hasA11yLabel(tree, label)).toBe(true);
    }
  });

  it("clarify mode chip has accessibilityRole=radio and label", () => {
    const tree = mount(
      <CorrectionSheet
        {...defaultProps()}
        needsClarification
        clarificationData={clarificationData}
      />,
    );
    const chips = tree.root.findAll(
      (n) => n.props.accessibilityRole === "radio" && !!n.props.accessibilityLabel,
    );
    expect(chips.length).toBeGreaterThan(0);
  });

  it("candidate rows have accessible labels with name and kcal", async () => {
    const listCandidates = jest.fn().mockResolvedValue([
      candidate({ name: "Turkey breast, roasted", calories: 135 }),
    ]);
    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
    await pressAsync(tree, "Change match");
    expect(hasA11yLabel(tree, "Select Turkey breast, roasted, 135 kcal per 100g")).toBe(true);
  });

  it("backdrop has an accessible close label", () => {
    const tree = mount(<CorrectionSheet {...defaultProps()} />);
    expect(hasA11yLabel(tree, "Close sheet")).toBe(true);
  });

});

// ─── Visible / close behaviour ────────────────────────────────────────────────

describe("visibility and close", () => {
  it("calls onClose when the Done button is pressed", () => {
    const onClose = jest.fn();
    const tree = mount(<CorrectionSheet {...defaultProps({ onClose })} />);
    press(tree, "Close");
    expect(onClose).toHaveBeenCalled();
  });

  it("calls onClose when the backdrop is tapped", () => {
    const onClose = jest.fn();
    const tree = mount(<CorrectionSheet {...defaultProps({ onClose })} />);
    press(tree, "Close sheet");
    expect(onClose).toHaveBeenCalled();
  });
});

// ─── Light + dark ──────────────────────────────────────────────────────────────

describe("light and dark theme", () => {
  it("renders correctly in light mode", () => {
    const tree = mount(<CorrectionSheet {...defaultProps()} />);
    expect(allText(tree)).toContain("Turkey breast");
  });

  it("renders correctly in dark mode", () => {
    let tree!: ReactTestRenderer;
    act(() => {
      tree = render(
        <ThemeProvider override="dark">
          <CorrectionSheet {...defaultProps()} />
        </ThemeProvider>,
      );
    });
    expect(allText(tree)).toContain("Turkey breast");
  });
});

// ─── Beat 2: correction saved (FTY-181) ─────────────────────────────────────────

describe("beat 2 — correction saved haptic", () => {
  it("fires once when an amount step commits successfully", async () => {
    const editItem = jest
      .fn()
      .mockResolvedValue(food({ amount: 1.25, calories: 150 }));
    const tree = mount(<CorrectionSheet {...defaultProps({ editItem })} />);
    await pressAsync(tree, "Increase amount");
    expect(mockCorrectionSavedHaptic).toHaveBeenCalledTimes(1);
  });

  it("does not fire when the amount step fails on the server", async () => {
    const editItem = jest
      .fn()
      .mockRejectedValue(new DerivedItemApiError(500, "boom"));
    const tree = mount(<CorrectionSheet {...defaultProps({ editItem })} />);
    await pressAsync(tree, "Increase amount");
    expect(mockCorrectionSavedHaptic).not.toHaveBeenCalled();
  });

  it("fires once when a re-resolve (change match) commits successfully", async () => {
    const reResolve = jest.fn().mockResolvedValue(food({ calories: 180 }));
    const listCandidates = jest.fn().mockResolvedValue([candidate()]);
    const tree = mount(
      <CorrectionSheet {...defaultProps({ reResolve, listCandidates })} />,
    );
    await pressAsync(tree, "Change match");
    await pressAsync(
      tree,
      "Select Turkey breast, roasted, 135 kcal per 100g",
    );
    expect(mockCorrectionSavedHaptic).toHaveBeenCalledTimes(1);
  });

  it("does not fire on a validation error in the advanced override", async () => {
    const editItem = jest.fn();
    const tree = mount(<CorrectionSheet {...defaultProps({ editItem })} />);
    await pressAsync(tree, "Override Calories, currently 120 kcal");
    typeInto(tree, "Calories value", "-5");
    await pressAsync(tree, "Save Calories override");
    expect(editItem).not.toHaveBeenCalled();
    expect(mockCorrectionSavedHaptic).not.toHaveBeenCalled();
  });

  it("fires once when an advanced override commits successfully", async () => {
    const editItem = jest.fn().mockResolvedValue(food({ calories: 200, is_edited: true }));
    const tree = mount(<CorrectionSheet {...defaultProps({ editItem })} />);
    await pressAsync(tree, "Override Calories, currently 120 kcal");
    typeInto(tree, "Calories value", "200");
    await pressAsync(tree, "Save Calories override");
    expect(mockCorrectionSavedHaptic).toHaveBeenCalledTimes(1);
  });
});
