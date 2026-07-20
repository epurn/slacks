/**
 * The CorrectionSheet clarify sub-flow: when an item needs a missing detail the
 * sheet presents the question, quick-pick chips, and a free-text fallback, and
 * never auto-fills the answer. Split out of `CorrectionSheet.test.tsx`
 * (FTY-415); shared fixtures/helpers live in `@/testUtils/correctionSheet`.
 */

import { CorrectionSheet } from "./CorrectionSheet";
import { cleanupReactTestRenderers } from "@/testUtils/reactTestRenderer";
import { mockReduceMotion } from "@/testUtils/reduceMotion";
import {
  allText,
  clarificationData,
  defaultProps,
  hasA11yLabel,
  mount,
  press,
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

  it("renders the free-text input + Done reachable in both states", () => {
    // The native sheet sizes the body via its detent, so the clarify body no
    // longer needs a manual min-height floor: the question, free-text input, and
    // Done are reachable for question-present and question-absent/loading alike.
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
