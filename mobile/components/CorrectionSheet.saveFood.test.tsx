/**
 * FTY-052/053: the CorrectionSheet "Save as food" sub-flow — offered only when
 * a log phrase is present, saves the current nutrition snapshot, shows a saved
 * state, surfaces a nonjudgmental error without echoing values, and is hidden in
 * change-match/override mode. Split out of `CorrectionSheet.test.tsx` (FTY-415);
 * shared fixtures/helpers live in `@/testUtils/correctionSheet`.
 */

import { CorrectionSheet } from "./CorrectionSheet";
import { SavedFoodApiError } from "@/api/savedFoods";
import { cleanupReactTestRenderers } from "@/testUtils/reactTestRenderer";
import { sourceCandidates } from "@/testUtils/correctionCandidates";
import { mockReduceMotion } from "@/testUtils/reduceMotion";
import {
  SESSION,
  allText,
  defaultProps,
  hasA11yLabel,
  mount,
  pressAsync,
  savedFoodResult,
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
    const listCandidates = jest.fn().mockResolvedValue(sourceCandidates());
    const tree = mount(
      <CorrectionSheet {...defaultProps({ listCandidates })} logPhrase="turkey" />,
    );
    await pressAsync(tree, "Change match");
    expect(hasA11yLabel(tree, "Save as food")).toBe(false);
  });
});
