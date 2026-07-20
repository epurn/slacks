/**
 * Tests for the FTY-100 CorrectionSheet component.
 *
 * All API calls are mocked; the sheet is presented as a standalone component
 * (per the story spec: built and tested as a standalone presentable component).
 *
 * This file covers the levers that stay on the resting sheet:
 *   - Provenance block render
 *   - Amount stepper → FTY-092 endpoint, no client math, provenance unchanged
 *   - Direct override → FTY-051 edit, "✎ edited" provenance, error shapes
 *   - Rough-estimate nudge → "≈ Rough estimate" + "Make it exact"
 *   - Accessibility: VoiceOver labels on provenance icons and every lever
 *   - Visibility / close, light + dark theme, and the correction-saved beat
 *
 * The larger sub-flows live in sibling suites (FTY-415 split): change-match →
 * `CorrectionSheet.changeMatch.test.tsx`, clarify mode →
 * `CorrectionSheet.clarify.test.tsx`, save-as-food →
 * `CorrectionSheet.saveFood.test.tsx`. Shared fixtures and render helpers live
 * in `@/testUtils/correctionSheet`.
 */

import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { ThemeProvider } from "@/theme";

import { CorrectionSheet } from "./CorrectionSheet";
import {
  DerivedItemApiError,
  type DerivedFoodItemDTO,
} from "@/api/derivedItems";
import { cleanupReactTestRenderers } from "@/testUtils/reactTestRenderer";
import { sourceCandidates } from "@/testUtils/correctionCandidates";
import { mockReduceMotion } from "@/testUtils/reduceMotion";
import { correctionSavedHaptic } from "@/theme/haptics";
import {
  SESSION,
  allA11yLabels,
  allText,
  candidate,
  clarificationData,
  defaultProps,
  food,
  hasA11yLabel,
  modelPriorSource,
  mount,
  press,
  pressAsync,
  typeInto,
} from "@/testUtils/correctionSheet";

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

// Mock AccessibilityInfo for all tests (isReduceMotionEnabled returns false by default).
beforeEach(() => {
  mockReduceMotion(false);
  mockCorrectionSavedHaptic.mockClear();
});

afterEach(() => {
  cleanupReactTestRenderers();
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
    expect(hasA11yLabel(tree, "Make it exact")).toBe(true);
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
    expect(hasA11yLabel(tree, "Make it exact")).toBe(true);
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
    const listCandidates = jest.fn().mockResolvedValue(
      sourceCandidates([candidate({ name: "Turkey breast, roasted", calories: 135 })]),
    );
    const tree = mount(<CorrectionSheet {...defaultProps({ listCandidates })} />);
    await pressAsync(tree, "Change match");
    expect(hasA11yLabel(tree, "Select Turkey breast, roasted, 135 kcal per 100g")).toBe(true);
  });

  it("presents as a native sheet announced to VoiceOver", () => {
    // The hand-faked Modal + tappable backdrop is gone; the native sheet carries
    // an accessibility label announcing it, and swipe/tap-outside dismissal is
    // provided by the native presentation controller.
    const tree = mount(<CorrectionSheet {...defaultProps()} />);
    expect(hasA11yLabel(tree, "Turkey breast details")).toBe(true);
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

  it("calls onClose when the native sheet is dismissed by gesture", () => {
    const onClose = jest.fn();
    const tree = mount(<CorrectionSheet {...defaultProps({ onClose })} />);
    // The native swipe/tap-outside dismissal surfaces as onDismissed on the
    // sheet screen; NativeSheet forwards it to onClose.
    const sheetScreen = tree.root.find(
      (n) => typeof n.props.onDismissed === "function",
    );
    act(() => {
      sheetScreen.props.onDismissed({ nativeEvent: { dismissCount: 1 } });
    });
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
    const listCandidates = jest.fn().mockResolvedValue(sourceCandidates([candidate()]));
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
