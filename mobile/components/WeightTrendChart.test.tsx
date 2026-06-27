import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { WeightTrendChart } from "./WeightTrendChart";
import type { WeightEntryDTO } from "@/api/weightEntries";

const TEST_WIDTH = 300;

function entry(overrides: Partial<WeightEntryDTO>): WeightEntryDTO {
  return {
    id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    user_id: "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
    weight_kg: 70.0,
    effective_date: "2026-06-27",
    created_at: "2026-06-27T08:00:00Z",
    updated_at: "2026-06-27T08:00:00Z",
    ...overrides,
  };
}

function render(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(element);
  });
  return tree;
}

function textContent(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

describe("WeightTrendChart — loading state", () => {
  it("shows an accessible loading indicator", () => {
    const tree = render(
      <WeightTrendChart
        entries={[]}
        unitsPreference="metric"
        loading
        error={null}
        width={TEST_WIDTH}
      />,
    );
    const indicator = tree.root.find(
      (n) => n.props.accessibilityLabel === "Loading your weight trend",
    );
    expect(indicator).toBeTruthy();
  });
});

describe("WeightTrendChart — error state", () => {
  it("shows the error message with an alert role", () => {
    const tree = render(
      <WeightTrendChart
        entries={[]}
        unitsPreference="metric"
        loading={false}
        error="Could not load your weight log."
        width={TEST_WIDTH}
      />,
    );
    const alertNode = tree.root.find((n) => n.props.accessibilityRole === "alert");
    expect(alertNode).toBeTruthy();
    expect(textContent(tree)).toContain("Could not load your weight log.");
  });

  it("shows a Try again button that calls onRetry", () => {
    const onRetry = jest.fn();
    const tree = render(
      <WeightTrendChart
        entries={[]}
        unitsPreference="metric"
        loading={false}
        error="Error"
        onRetry={onRetry}
        width={TEST_WIDTH}
      />,
    );
    const retryBtn = tree.root.find(
      (n) => n.props.accessibilityLabel === "Try again",
    );
    act(() => {
      retryBtn.props.onPress();
    });
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

describe("WeightTrendChart — empty state", () => {
  it("shows a helpful empty-state message", () => {
    const tree = render(
      <WeightTrendChart
        entries={[]}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    expect(textContent(tree)).toContain("No weight entries yet");
  });
});

describe("WeightTrendChart — single-point (sparse) state", () => {
  it("renders the single entry value in metric units", () => {
    const tree = render(
      <WeightTrendChart
        entries={[entry({ weight_kg: 70, effective_date: "2026-06-27" })]}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    expect(textContent(tree)).toContain("70");
    expect(textContent(tree)).toContain("kg");
    expect(textContent(tree)).toContain("2026-06-27");
  });

  it("converts a single entry to lb for imperial users", () => {
    const tree = render(
      <WeightTrendChart
        entries={[entry({ weight_kg: 70, effective_date: "2026-06-27" })]}
        unitsPreference="imperial"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    // 70 kg ÷ 0.45359237 ≈ 154.3 lb
    expect(textContent(tree)).toContain("lb");
    expect(textContent(tree)).not.toContain("kg");
  });

  it("carries an accessible summary label for the single point", () => {
    const tree = render(
      <WeightTrendChart
        entries={[entry({ weight_kg: 70, effective_date: "2026-06-27" })]}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    const imageNode = tree.root.find((n) => n.props.accessibilityRole === "image");
    expect(imageNode.props.accessibilityLabel).toContain("70");
    expect(imageNode.props.accessibilityLabel).toContain("kg");
  });
});

describe("WeightTrendChart — multiple entries", () => {
  const ENTRIES: readonly WeightEntryDTO[] = [
    entry({ id: "1", weight_kg: 70, effective_date: "2026-06-01" }),
    entry({ id: "2", weight_kg: 71, effective_date: "2026-06-10" }),
    entry({ id: "3", weight_kg: 72, effective_date: "2026-06-27" }),
  ];

  it("renders without crashing for multiple entries", () => {
    const tree = render(
      <WeightTrendChart
        entries={ENTRIES}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    expect(tree.toJSON()).not.toBeNull();
  });

  it("carries an accessible summary label describing the trend", () => {
    const tree = render(
      <WeightTrendChart
        entries={ENTRIES}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    const imageNode = tree.root.find((n) => n.props.accessibilityRole === "image");
    expect(imageNode.props.accessibilityLabel).toContain("3 entries");
    expect(imageNode.props.accessibilityLabel).toContain("2026-06-01");
    expect(imageNode.props.accessibilityLabel).toContain("2026-06-27");
  });

  it("shows axis labels in metric units", () => {
    const tree = render(
      <WeightTrendChart
        entries={ENTRIES}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    // Chart renders min and max y-axis labels
    expect(textContent(tree)).toContain("kg");
  });

  it("shows axis labels in imperial units for imperial users", () => {
    const tree = render(
      <WeightTrendChart
        entries={ENTRIES}
        unitsPreference="imperial"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    expect(textContent(tree)).toContain("lb");
    expect(textContent(tree)).not.toContain("kg");
  });

  it("renders line-segment views between data points", () => {
    const tree = render(
      <WeightTrendChart
        entries={ENTRIES}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    // n-1 = 2 unique segment testIDs (each testID appears once per composite/host pair)
    const segmentIds = new Set(
      tree.root
        .findAll((n) => typeof n.props.testID === "string" && n.props.testID.startsWith("weight-segment-"))
        .map((n) => n.props.testID as string),
    );
    expect(segmentIds.size).toBe(2);
  });

  it("renders dot views for each data point", () => {
    const tree = render(
      <WeightTrendChart
        entries={ENTRIES}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    // 3 unique dot testIDs
    const dotIds = new Set(
      tree.root
        .findAll((n) => typeof n.props.testID === "string" && n.props.testID.startsWith("weight-dot-"))
        .map((n) => n.props.testID as string),
    );
    expect(dotIds.size).toBe(3);
  });

  it("does not render a chart canvas when width is 0 (unmeasured)", () => {
    const tree = render(
      <WeightTrendChart
        entries={ENTRIES}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={0}
      />,
    );
    // No segment or dot views when canvas is not measured
    const segmentIds = new Set(
      tree.root
        .findAll((n) => typeof n.props.testID === "string" && n.props.testID.startsWith("weight-segment-"))
        .map((n) => n.props.testID as string),
    );
    expect(segmentIds.size).toBe(0);
  });
});
