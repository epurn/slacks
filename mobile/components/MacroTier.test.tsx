import { act, create as render, type ReactTestRenderer } from "react-test-renderer";

import { MacroTier } from "./MacroTier";

function allA11yLabels(tree: ReactTestRenderer): string[] {
  return tree.root
    .findAll((n) => !!n.props.accessibilityLabel)
    .map((n) => n.props.accessibilityLabel as string);
}

function allText(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

describe("MacroTier", () => {
  it("renders P/C/F chips with consumed grams", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <MacroTier protein_g={80} carbs_g={150} fat_g={40} active_calories={0} />,
      );
    });

    const labels = allA11yLabels(tree!);
    expect(labels).toContain("Protein: 80g");
    expect(labels).toContain("Carbs: 150g");
    expect(labels).toContain("Fat: 40g");
  });

  it("rounds fractional grams to nearest integer", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <MacroTier protein_g={80.7} carbs_g={149.2} fat_g={40.5} active_calories={0} />,
      );
    });

    const labels = allA11yLabels(tree!);
    expect(labels).toContain("Protein: 81g");
    expect(labels).toContain("Carbs: 149g");
    expect(labels).toContain("Fat: 41g");
  });

  it("renders exercise burn as a distinct line with a11y label", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <MacroTier protein_g={80} carbs_g={150} fat_g={40} active_calories={300} />,
      );
    });

    const labels = allA11yLabels(tree!);
    expect(labels).toContain("Burned: 300 kcal");

    // Burn line text is present
    const text = allText(tree!);
    expect(text).toContain("burned");
  });

  it("exercise line is not shown when active_calories is 0", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <MacroTier protein_g={80} carbs_g={150} fat_g={40} active_calories={0} />,
      );
    });

    const labels = allA11yLabels(tree!);
    expect(labels.some((l) => l.includes("Burned"))).toBe(false);

    const text = allText(tree!);
    expect(text).not.toContain("burned");
  });

  it("exercise is not folded into the P/C/F chips — macro chips are P, C, F only", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <MacroTier protein_g={80} carbs_g={150} fat_g={40} active_calories={210} />,
      );
    });

    // All three macro types are present and exercise is NOT a fourth macro chip
    const labels = allA11yLabels(tree!);
    expect(labels.some((l) => l.startsWith("Protein:"))).toBe(true);
    expect(labels.some((l) => l.startsWith("Carbs:"))).toBe(true);
    expect(labels.some((l) => l.startsWith("Fat:"))).toBe(true);
    // Exercise burn is a separate row, not a macro chip label
    const exerciseAsChip = labels.filter(
      (l) => l.startsWith("Exercise:") || l.startsWith("Burn:") || l.startsWith("Calories burned:"),
    );
    expect(exerciseAsChip).toHaveLength(0);
  });
});
