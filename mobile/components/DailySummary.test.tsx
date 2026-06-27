import { act, create as render, type ReactTestRenderer } from "react-test-renderer";

import { DailySummary } from "./DailySummary";
import type { DailySummaryDTO } from "@/api/dailySummary";

function mockSummary(overrides: Partial<DailySummaryDTO>): DailySummaryDTO {
  return {
    date: "2026-06-27",
    intake: {
      calories: 1234.5,
      protein_g: 80.0,
      carbs_g: 150.0,
      fat_g: 40.0,
    },
    target: {
      calories: 1800,
    },
    exercise: {
      active_calories: 210.0,
    },
    ...overrides,
  };
}

describe("DailySummary", () => {
  it("renders the four separated figures from a daily summary response", () => {
    const summary = mockSummary({});
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<DailySummary summary={summary} />);
    });

    const a11yLabels = tree!.root
      .findAll((n) => n.props.accessibilityLabel)
      .map((n) => n.props.accessibilityLabel as string)
      .join(" ");

    expect(a11yLabels).toContain("Intake: 1235 calories");
    expect(a11yLabels).toContain("Protein: 80 grams");
    expect(a11yLabels).toContain("Carbs: 150 grams");
    expect(a11yLabels).toContain("Fat: 40 grams");
    expect(a11yLabels).toContain("Target: 1800 calories");
    expect(a11yLabels).toContain("Exercise burn: 210 calories");
  });

  it("displays intake and exercise burn as distinct values (not conflated)", () => {
    const summary = mockSummary({
      intake: {
        calories: 1500.0,
        protein_g: 100.0,
        carbs_g: 150.0,
        fat_g: 50.0,
      },
      exercise: {
        active_calories: 300.0,
      },
    });

    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<DailySummary summary={summary} />);
    });

    const a11yLabels = tree!.root
      .findAll((n) => n.props.accessibilityLabel)
      .map((n) => n.props.accessibilityLabel as string);

    expect(a11yLabels).toContain("Intake: 1500 calories");
    expect(a11yLabels).toContain("Exercise burn: 300 calories");
  });

  it("renders gracefully with empty-day state (zeroed totals)", () => {
    const summary = mockSummary({
      intake: {
        calories: 0.0,
        protein_g: 0.0,
        carbs_g: 0.0,
        fat_g: 0.0,
      },
      target: {
        calories: 2000,
      },
      exercise: {
        active_calories: 0.0,
      },
    });

    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<DailySummary summary={summary} />);
    });

    const a11yLabels = tree!.root
      .findAll((n) => n.props.accessibilityLabel)
      .map((n) => n.props.accessibilityLabel as string)
      .join(" ");

    expect(a11yLabels).toContain("Intake: 0 calories");
    expect(a11yLabels).toContain("Target: 2000 calories");
  });

  it("handles missing target (null) gracefully", () => {
    const summary = mockSummary({
      target: null,
    });

    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<DailySummary summary={summary} />);
    });

    const text = tree!.root
      .findAll((n) => typeof n.props.children === "string")
      .map((n) => n.props.children as string)
      .join(" ");

    expect(text).toContain("Intake");
    expect(text).toContain("Exercise");
    expect(text).not.toContain("Target");
  });


  it("renders an error state", () => {
    const errorMsg = "We couldn't load your summary. Check your connection and try again.";
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <DailySummary
          summary={null}
          error={errorMsg}
        />,
      );
    });

    const text = tree!.root
      .findAll((n) => typeof n.props.children === "string")
      .map((n) => n.props.children as string)
      .join(" ");

    expect(text).toContain(errorMsg);
  });

  it("reconciles to new figures when summary is updated", () => {
    const initial = mockSummary({
      intake: { calories: 1000.0, protein_g: 50.0, carbs_g: 100.0, fat_g: 30.0 },
    });
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<DailySummary summary={initial} />);
    });

    let a11yLabels = tree!.root
      .findAll((n) => n.props.accessibilityLabel)
      .map((n) => n.props.accessibilityLabel as string)
      .join(" ");
    expect(a11yLabels).toContain("Intake: 1000 calories");

    const updated = mockSummary({
      intake: { calories: 1500.0, protein_g: 80.0, carbs_g: 150.0, fat_g: 40.0 },
    });
    act(() => {
      tree!.update(<DailySummary summary={updated} />);
    });

    a11yLabels = tree!.root
      .findAll((n) => n.props.accessibilityLabel)
      .map((n) => n.props.accessibilityLabel as string)
      .join(" ");
    expect(a11yLabels).toContain("Intake: 1500 calories");
  });

  it("provides accessible labels on each figure", () => {
    const summary = mockSummary({
      intake: {
        calories: 1234.5,
        protein_g: 80.2,
        carbs_g: 150.5,
        fat_g: 40.1,
      },
      target: { calories: 1800 },
      exercise: { active_calories: 210.3 },
    });

    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<DailySummary summary={summary} />);
    });

    const a11yLabels = tree!.root
      .findAll((n) => n.props.accessibilityLabel)
      .map((n) => n.props.accessibilityLabel as string);

    expect(a11yLabels).toContain("Intake: 1235 calories");
    expect(a11yLabels).toContain("Protein: 80 grams");
    expect(a11yLabels).toContain("Carbs: 151 grams");
    expect(a11yLabels).toContain("Fat: 40 grams");
    expect(a11yLabels).toContain("Target: 1800 calories");
    expect(a11yLabels).toContain("Exercise burn: 210 calories");
  });

  it("returns null when no summary and not loading/error", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<DailySummary />);
    });

    expect(tree!.root.instance).toBeNull();
  });

  it("rounds figures to nearest integer for display", () => {
    const summary = mockSummary({
      intake: {
        calories: 1234.7,
        protein_g: 80.4,
        carbs_g: 150.9,
        fat_g: 40.1,
      },
      exercise: { active_calories: 210.6 },
    });

    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<DailySummary summary={summary} />);
    });

    const a11yLabels = tree!.root
      .findAll((n) => n.props.accessibilityLabel)
      .map((n) => n.props.accessibilityLabel as string)
      .join(" ");

    expect(a11yLabels).toContain("Intake: 1235 calories");
    expect(a11yLabels).toContain("Protein: 80 grams");
    expect(a11yLabels).toContain("Carbs: 151 grams");
    expect(a11yLabels).toContain("Fat: 40 grams");
    expect(a11yLabels).toContain("Exercise burn: 211 calories");
  });
});
