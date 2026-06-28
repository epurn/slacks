import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { EWMATrendChart } from "./EWMATrendChart";
import type { WeightEntryDTO } from "@/api/weightEntries";
import { computeEWMAFromEntries } from "@/state/trends";

const TEST_WIDTH = 320;

function entry(
  id: string,
  weight_kg: number,
  date: string,
): WeightEntryDTO {
  return {
    id,
    user_id: "uid",
    weight_kg,
    effective_date: date,
    created_at: `${date}T08:00:00Z`,
    updated_at: `${date}T08:00:00Z`,
  };
}

const ENTRIES: readonly WeightEntryDTO[] = [
  entry("1", 70, "2026-06-01"),
  entry("2", 71, "2026-06-10"),
  entry("3", 72, "2026-06-20"),
];
const EWMA_KG = computeEWMAFromEntries(ENTRIES);

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

// ─────────────────────────────────────────────────────────────────────────────
// Loading
// ─────────────────────────────────────────────────────────────────────────────

describe("EWMATrendChart — loading", () => {
  it("shows an accessible loading indicator", () => {
    const tree = render(
      <EWMATrendChart
        entries={[]}
        ewmaKg={[]}
        unitsPreference="metric"
        loading
        error={null}
        width={TEST_WIDTH}
      />,
    );
    const ind = tree.root.find(
      (n) => n.props.accessibilityLabel === "Loading weight trend",
    );
    expect(ind).toBeTruthy();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Error
// ─────────────────────────────────────────────────────────────────────────────

describe("EWMATrendChart — error", () => {
  it("shows error text with alert role", () => {
    const tree = render(
      <EWMATrendChart
        entries={[]}
        ewmaKg={[]}
        unitsPreference="metric"
        loading={false}
        error="Could not load trend"
        width={TEST_WIDTH}
      />,
    );
    const alert = tree.root.find((n) => n.props.accessibilityRole === "alert");
    expect(alert).toBeTruthy();
    expect(textContent(tree)).toContain("Could not load trend");
  });

  it("shows retry button that calls onRetry", () => {
    const onRetry = jest.fn();
    const tree = render(
      <EWMATrendChart
        entries={[]}
        ewmaKg={[]}
        unitsPreference="metric"
        loading={false}
        error="Error"
        onRetry={onRetry}
        width={TEST_WIDTH}
      />,
    );
    const retry = tree.root.find(
      (n) => n.props.accessibilityLabel === "Try again",
    );
    act(() => retry.props.onPress());
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Empty state
// ─────────────────────────────────────────────────────────────────────────────

describe("EWMATrendChart — empty", () => {
  it("shows the calm invite 'Log your first weigh-in'", () => {
    const tree = render(
      <EWMATrendChart
        entries={[]}
        ewmaKg={[]}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    expect(textContent(tree)).toContain("Log your first weigh-in");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Single-point (sparse)
// ─────────────────────────────────────────────────────────────────────────────

describe("EWMATrendChart — single point", () => {
  const singleEntry = [entry("1", 70, "2026-06-27")];
  const singleEwma = computeEWMAFromEntries(singleEntry);

  it("renders the EWMA smoothed value in metric units", () => {
    const tree = render(
      <EWMATrendChart
        entries={singleEntry}
        ewmaKg={singleEwma}
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

  it("converts to lb for imperial users", () => {
    const tree = render(
      <EWMATrendChart
        entries={singleEntry}
        ewmaKg={singleEwma}
        unitsPreference="imperial"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    expect(textContent(tree)).toContain("lb");
    expect(textContent(tree)).not.toContain("kg");
  });

  it("carries a text alternative label (image role)", () => {
    const tree = render(
      <EWMATrendChart
        entries={singleEntry}
        ewmaKg={singleEwma}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    const img = tree.root.find((n) => n.props.accessibilityRole === "image");
    expect(img.props.accessibilityLabel).toBeTruthy();
    expect(img.props.accessibilityLabel).toContain("2026-06-27");
  });

  it("renders without crash for sparse single-point range (no startup artifact)", () => {
    expect(() =>
      render(
        <EWMATrendChart
          entries={singleEntry}
          ewmaKg={singleEwma}
          unitsPreference="metric"
          loading={false}
          error={null}
          width={TEST_WIDTH}
        />,
      ),
    ).not.toThrow();
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Multiple entries
// ─────────────────────────────────────────────────────────────────────────────

describe("EWMATrendChart — multiple entries", () => {
  it("renders EWMA segment views between data points", () => {
    const tree = render(
      <EWMATrendChart
        entries={ENTRIES}
        ewmaKg={EWMA_KG}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    const segIds = new Set(
      tree.root
        .findAll(
          (n) =>
            typeof n.props.testID === "string" &&
            n.props.testID.startsWith("ewma-segment-"),
        )
        .map((n) => n.props.testID as string),
    );
    // n-1 = 2 segments for 3 entries
    expect(segIds.size).toBe(2);
  });

  it("renders raw dot views for each data point (de-emphasised)", () => {
    const tree = render(
      <EWMATrendChart
        entries={ENTRIES}
        ewmaKg={EWMA_KG}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    const dotIds = new Set(
      tree.root
        .findAll(
          (n) =>
            typeof n.props.testID === "string" &&
            n.props.testID.startsWith("ewma-raw-dot-"),
        )
        .map((n) => n.props.testID as string),
    );
    expect(dotIds.size).toBe(3);
  });

  it("carries an accessible text summary describing the trend", () => {
    const tree = render(
      <EWMATrendChart
        entries={ENTRIES}
        ewmaKg={EWMA_KG}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    const img = tree.root.find((n) => n.props.accessibilityRole === "image");
    const label = img.props.accessibilityLabel as string;
    // Must describe the trend, not just the number
    expect(label).toContain("trend");
    expect(label).toContain("2026-06-01");
    expect(label).toContain("2026-06-20");
  });

  it("does not render the chart canvas when width is 0 (unmeasured)", () => {
    const tree = render(
      <EWMATrendChart
        entries={ENTRIES}
        ewmaKg={EWMA_KG}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={0}
      />,
    );
    const segIds = tree.root.findAll(
      (n) =>
        typeof n.props.testID === "string" &&
        n.props.testID.startsWith("ewma-segment-"),
    );
    expect(segIds).toHaveLength(0);
  });

  it("shows axis labels in the user's units", () => {
    const tree = render(
      <EWMATrendChart
        entries={ENTRIES}
        ewmaKg={EWMA_KG}
        unitsPreference="metric"
        loading={false}
        error={null}
        width={TEST_WIDTH}
      />,
    );
    expect(textContent(tree)).toContain("kg");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Trend smoothing render (the EWMA-specific quality property)
// ─────────────────────────────────────────────────────────────────────────────

describe("EWMATrendChart — trend smoothing render", () => {
  it("renders without crash for a noisy series that includes a spike", () => {
    // Spike on day 4
    const noisyEntries = [
      entry("1", 70, "2026-06-01"),
      entry("2", 70, "2026-06-02"),
      entry("3", 70, "2026-06-03"),
      entry("4", 80, "2026-06-04"), // spike
      entry("5", 70, "2026-06-05"),
    ];
    const ewma = computeEWMAFromEntries(noisyEntries);
    expect(() =>
      render(
        <EWMATrendChart
          entries={noisyEntries}
          ewmaKg={ewma}
          unitsPreference="metric"
          loading={false}
          error={null}
          width={TEST_WIDTH}
        />,
      ),
    ).not.toThrow();
  });
});
