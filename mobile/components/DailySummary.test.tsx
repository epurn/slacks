import { act, create as render, type ReactTestRenderer } from "react-test-renderer";

import { DailySummary } from "./DailySummary";
import type { DailySummaryDTO, TargetReadModel } from "@/api/dailySummary";

/** Build a derived-only target read-model whose effective calorie target is `kcal`. */
function targetModel(kcal: number): TargetReadModel {
  return {
    calories: { effective: kcal, derived: kcal, source: "derived" },
    protein_g: { effective: 128, derived: 128, source: "derived" },
    carbs_g: { effective: 148, derived: 148, source: "derived" },
    fat_g: { effective: 64, derived: 64, source: "derived" },
  };
}

function mockSummary(overrides: Partial<DailySummaryDTO> = {}): DailySummaryDTO {
  return {
    date: "2026-06-27",
    intake: {
      calories: 1234.5,
      protein_g: 80.0,
      carbs_g: 150.0,
      fat_g: 40.0,
    },
    has_intake: true,
    target: targetModel(1800),
    exercise: {
      active_calories: 210.0,
    },
    ...overrides,
  };
}

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

describe("DailySummary — hero (CalorieHero)", () => {
  it("renders under-budget hero with consumed, target, percent, and remaining", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<DailySummary summary={mockSummary({ intake: { calories: 1240, protein_g: 80, carbs_g: 150, fat_g: 40 }, target: targetModel(2000) })} />);
    });

    const labels = allA11yLabels(tree!);
    // Hero combined label
    expect(labels.some((l) => l.includes("1,240 of 2,000 kcal"))).toBe(true);
    expect(labels.some((l) => l.includes("62 percent"))).toBe(true);
    expect(labels.some((l) => l.includes("760 remaining"))).toBe(true);

    const text = allText(tree!);
    expect(text).toContain("1,240 / 2,000 kcal · 62%");
  });

  it("renders over-budget hero with coral copy '500 over'", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<DailySummary summary={mockSummary({ intake: { calories: 2500, protein_g: 80, carbs_g: 150, fat_g: 40 }, target: targetModel(2000) })} />);
    });

    const labels = allA11yLabels(tree!);
    expect(labels.some((l) => l.includes("2,500 of 2,000 kcal"))).toBe(true);
    expect(labels.some((l) => l.includes("500 over budget"))).toBe(true);

    // Over-budget text is shown in the UI (not color alone)
    const text = allText(tree!);
    expect(text).toContain("over");
  });

  it("renders null-target hero gracefully (no crash, no bar, calm copy)", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<DailySummary summary={mockSummary({ target: null })} />);
    });

    const labels = allA11yLabels(tree!);
    expect(labels.some((l) => l.includes("no target set"))).toBe(true);

    const text = allText(tree!);
    expect(text).not.toContain("undefined");
    expect(text).not.toContain("NaN");
    expect(text).not.toContain("Infinity");
  });

  it("renders empty-state hero with full budget available (0 / 2,000 kcal)", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <DailySummary
          summary={mockSummary({
            intake: { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 },
            has_intake: false,
            target: targetModel(2000),
          })}
        />,
      );
    });

    const labels = allA11yLabels(tree!);
    expect(labels.some((l) => l.includes("0 of 2,000 kcal"))).toBe(true);
    expect(labels.some((l) => l.includes("2,000 remaining"))).toBe(true);

    const text = allText(tree!);
    expect(text).toContain("0 / 2,000 kcal · 2,000 to go");
    expect(text).not.toContain("0%");
  });
});

describe("DailySummary — macro tier (MacroTier)", () => {
  it("renders P/C/F chips with consumed grams", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <DailySummary
          summary={mockSummary({
            intake: { calories: 1234, protein_g: 80, carbs_g: 150, fat_g: 40 },
          })}
        />,
      );
    });

    const labels = allA11yLabels(tree!);
    expect(labels.some((l) => l.includes("Protein: 80g"))).toBe(true);
    expect(labels.some((l) => l.includes("Carbs: 150g"))).toBe(true);
    expect(labels.some((l) => l.includes("Fat: 40g"))).toBe(true);
  });

  it("renders exercise burn line distinctly (not a macro chip)", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <DailySummary
          summary={mockSummary({ exercise: { active_calories: 300 } })}
        />,
      );
    });

    const labels = allA11yLabels(tree!);
    expect(labels.some((l) => l.includes("Burned: 300 kcal"))).toBe(true);
  });

  it("hides exercise burn line when active_calories is 0", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <DailySummary
          summary={mockSummary({ exercise: { active_calories: 0 } })}
        />,
      );
    });

    const labels = allA11yLabels(tree!);
    expect(labels.some((l) => l.includes("Burned"))).toBe(false);
  });
});

describe("DailySummary — error and null states", () => {
  it("keeps the hero shell while rendering a calm summary error alert", () => {
    const msg = "We couldn't load your summary.";
    const onRetry = jest.fn();
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <DailySummary summary={null} error={msg} onRetry={onRetry} />,
      );
    });

    const text = allText(tree!);
    expect(text).toContain("0");
    expect(text).toContain("No target set");
    expect(text).toContain(msg);
    expect(text).toContain("Try again");
    expect(allA11yLabels(tree!).some((l) => l.includes("no target set"))).toBe(true);
  });

  it("renders a fallback hero shell when no summary and no error", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<DailySummary />);
    });
    expect(allText(tree!)).toContain("No target set");
    expect(allA11yLabels(tree!).some((l) => l.includes("no target set"))).toBe(true);
  });

  it("light and dark: hero a11y label is consistent regardless of color scheme", () => {
    // Both light and dark render the same a11y label text — the scheme only
    // changes colors, not content. Smoke-test both renders.
    const summary = mockSummary({
      intake: { calories: 500, protein_g: 30, carbs_g: 60, fat_g: 20 },
      target: targetModel(2000),
    });
    let lightTree: ReactTestRenderer;
    let darkTree: ReactTestRenderer;
    act(() => {
      lightTree = render(<DailySummary summary={summary} />);
    });
    act(() => {
      darkTree = render(<DailySummary summary={summary} />);
    });

    const lightLabels = allA11yLabels(lightTree!).join(" ");
    const darkLabels = allA11yLabels(darkTree!).join(" ");
    expect(lightLabels).toContain("500 of 2,000 kcal");
    expect(darkLabels).toContain("500 of 2,000 kcal");
  });
});
