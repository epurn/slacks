import { AccessibilityInfo, Animated } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { Circle, Polyline } from "react-native-svg";

import { EWMATrendChart } from "./EWMATrendChart";
import type { WeightEntryDTO } from "@/api/weightEntries";
import { computeEWMAFromEntries } from "@/state/trends";
import { mockReduceMotion } from "@/testUtils/reduceMotion";
import { lightPalette, typeScale } from "@/theme";
import { reducedMotionDuration } from "@/theme/motion";

// Tests render with the default (light) theme, so the chart draws with the
// light palette's accent / secondary colours.
const RAW_DOT_R = 3;
const TREND_DOT_R = 4;
const RAW_DOT_OPACITY = 0.35;
const DRAW_IN_MS = 400;

// A fake Animated driver so the draw-in settles deterministically and no
// animation loop keeps ticking after a test tears down (CalorieHero.test
// precedent). Auto-finishes by default; a test that needs the mid-reveal frame
// sets `autoFinishAnimations = false` and completes via `pendingAnimations`.
type AnimCallback = (result: { finished: boolean }) => void;
let pendingAnimations: AnimCallback[] = [];
let autoFinishAnimations = true;
const FAKE_ANIM = {
  start: (cb?: AnimCallback) => {
    if (autoFinishAnimations) cb?.({ finished: true });
    else if (cb) pendingAnimations.push(cb);
  },
  stop: () => {},
};
let timingSpy: jest.SpyInstance;

/** The draw-in's own timing calls (its reveal duration), ignoring any other. */
function drawInTimings() {
  return timingSpy.mock.calls.filter(
    ([, cfg]) => (cfg as { duration?: number }).duration === DRAW_IN_MS,
  );
}

beforeEach(() => {
  // Reduce Motion off by default so the draw-in takes its reveal path.
  mockReduceMotion(false);
  pendingAnimations = [];
  autoFinishAnimations = true;
  timingSpy = jest.spyOn(Animated, "timing").mockReturnValue(FAKE_ANIM as never);
});

afterEach(() => {
  jest.restoreAllMocks();
});

function flattenedStyle(style: unknown): Record<string, unknown> {
  if (Array.isArray(style)) {
    return Object.assign({}, ...style.map(flattenedStyle));
  }
  return typeof style === "object" && style !== null
    ? (style as Record<string, unknown>)
    : {};
}

function rawCircles(tree: ReactTestRenderer) {
  return tree.root
    .findAllByType(Circle)
    .filter((n) => n.props.fill === lightPalette.textSecondary);
}

function trendCircles(tree: ReactTestRenderer) {
  return tree.root
    .findAllByType(Circle)
    .filter((n) => n.props.fill === lightPalette.accent);
}

const TEST_WIDTH = 320;
// A fixed "today" well after every fixture date, so all dates human-format to
// "{Month} {Day}" (never "Today"/"Yesterday") for stable assertions.
const TEST_TODAY = "2026-07-01";

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
        today={TEST_TODAY}
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
        today={TEST_TODAY}
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
        today={TEST_TODAY}
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
        today={TEST_TODAY}
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
        today={TEST_TODAY}
        width={TEST_WIDTH}
      />,
    );
    expect(textContent(tree)).toContain("70");
    expect(textContent(tree)).toContain("kg");
    // User-facing date is human-formatted, never raw ISO (FTY-189).
    expect(textContent(tree)).toContain("June 27");
    expect(textContent(tree)).not.toContain("2026-06-27");
  });

  it("converts to lb for imperial users", () => {
    const tree = render(
      <EWMATrendChart
        entries={singleEntry}
        ewmaKg={singleEwma}
        unitsPreference="imperial"
        loading={false}
        error={null}
        today={TEST_TODAY}
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
        today={TEST_TODAY}
        width={TEST_WIDTH}
      />,
    );
    const img = tree.root.find((n) => n.props.accessibilityRole === "image");
    expect(img.props.accessibilityLabel).toBeTruthy();
    expect(img.props.accessibilityLabel).toContain("June 27");
    expect(img.props.accessibilityLabel).not.toContain("2026-06-27");
  });

  it("renders the smoothed value through the display face (tabular-nums, per typeScale.title2)", () => {
    const tree = render(
      <EWMATrendChart
        entries={singleEntry}
        ewmaKg={singleEwma}
        unitsPreference="metric"
        loading={false}
        error={null}
        today={TEST_TODAY}
        width={TEST_WIDTH}
      />,
    );
    const valueNode = tree.root.find(
      (n) =>
        (n.type as unknown as string) === "Text" &&
        typeof n.props.children === "string" &&
        (n.props.children as string).includes("kg"),
    );
    const styles: Array<Record<string, unknown>> = Array.isArray(valueNode.props.style)
      ? valueNode.props.style
      : [valueNode.props.style];
    const combined = Object.assign({}, ...styles);
    expect(combined.fontVariant).toEqual(["tabular-nums"]);
    expect(combined.fontSize).toBe(typeScale.title2);
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
          today={TEST_TODAY}
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
  it("draws the EWMA trend as one SVG polyline through every point, left to right", () => {
    const tree = render(
      <EWMATrendChart
        entries={ENTRIES}
        ewmaKg={EWMA_KG}
        unitsPreference="metric"
        loading={false}
        error={null}
        today={TEST_TODAY}
        width={TEST_WIDTH}
      />,
    );
    const lines = tree.root.findAllByType(Polyline);
    // Exactly one polyline is the trend line (not n-1 rotated segments).
    expect(lines).toHaveLength(1);
    const line = lines[0]!;
    expect(line.props.stroke).toBe(lightPalette.accent);
    expect(line.props.strokeWidth).toBe(3);
    expect(line.props.fill).toBe("none");

    // Its points pass through all 3 entries, in ascending x order.
    const pairs = (line.props.points as string)
      .trim()
      .split(/\s+/)
      .map((pt) => pt.split(",").map(Number) as [number, number]);
    expect(pairs).toHaveLength(ENTRIES.length);
    const xs = pairs.map(([x]) => x);
    for (let i = 1; i < xs.length; i++) {
      expect(xs[i]!).toBeGreaterThan(xs[i - 1]!);
    }
  });

  it("draws a raw SVG circle per weigh-in, de-emphasised", () => {
    const tree = render(
      <EWMATrendChart
        entries={ENTRIES}
        ewmaKg={EWMA_KG}
        unitsPreference="metric"
        loading={false}
        error={null}
        today={TEST_TODAY}
        width={TEST_WIDTH}
      />,
    );
    const raw = rawCircles(tree);
    expect(raw).toHaveLength(ENTRIES.length);
    for (const c of raw) {
      expect(c.props.r).toBe(RAW_DOT_R);
      expect(c.props.opacity).toBe(RAW_DOT_OPACITY);
    }
  });

  it("draws a trend SVG circle per point in the accent colour", () => {
    const tree = render(
      <EWMATrendChart
        entries={ENTRIES}
        ewmaKg={EWMA_KG}
        unitsPreference="metric"
        loading={false}
        error={null}
        today={TEST_TODAY}
        width={TEST_WIDTH}
      />,
    );
    const trend = trendCircles(tree);
    expect(trend).toHaveLength(ENTRIES.length);
    for (const c of trend) {
      expect(c.props.r).toBe(TREND_DOT_R);
    }
  });

  it("carries an accessible text summary describing the trend", () => {
    const tree = render(
      <EWMATrendChart
        entries={ENTRIES}
        ewmaKg={EWMA_KG}
        unitsPreference="metric"
        loading={false}
        error={null}
        today={TEST_TODAY}
        width={TEST_WIDTH}
      />,
    );
    const img = tree.root.find((n) => n.props.accessibilityRole === "image");
    const label = img.props.accessibilityLabel as string;
    // Must describe the trend, not just the number
    expect(label).toContain("trend");
    // Dates read as human prose, never raw ISO (FTY-189).
    expect(label).toContain("June 1");
    expect(label).toContain("June 20");
    expect(label).not.toContain("2026-06-01");
  });

  it("does not render the chart canvas when width is 0 (unmeasured)", () => {
    const tree = render(
      <EWMATrendChart
        entries={ENTRIES}
        ewmaKg={EWMA_KG}
        unitsPreference="metric"
        loading={false}
        error={null}
        today={TEST_TODAY}
        width={0}
      />,
    );
    // No SVG plot primitives render until a positive width arrives.
    expect(tree.root.findAllByType(Polyline)).toHaveLength(0);
    expect(tree.root.findAllByType(Circle)).toHaveLength(0);
  });

  it("shows axis labels in the user's units", () => {
    const tree = render(
      <EWMATrendChart
        entries={ENTRIES}
        ewmaKg={EWMA_KG}
        unitsPreference="metric"
        loading={false}
        error={null}
        today={TEST_TODAY}
        width={TEST_WIDTH}
      />,
    );
    expect(textContent(tree)).toContain("kg");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Trend smoothing render (the EWMA-specific quality property)
// ─────────────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────────────
// Draw-in (FTY-380)
// ─────────────────────────────────────────────────────────────────────────────

const MORE_ENTRIES: readonly WeightEntryDTO[] = [
  ...ENTRIES,
  entry("4", 71.5, "2026-06-27"),
];
const MORE_EWMA_KG = computeEWMAFromEntries(MORE_ENTRIES);

function chartWith(
  entries: readonly WeightEntryDTO[],
  ewmaKg: readonly number[],
  loading = false,
  rangeKey = "1M",
) {
  return (
    <EWMATrendChart
      entries={entries}
      ewmaKg={ewmaKg}
      unitsPreference="metric"
      loading={loading}
      error={null}
      today={TEST_TODAY}
      width={TEST_WIDTH}
      rangeKey={rangeKey}
    />
  );
}

function canvasOpacity(tree: ReactTestRenderer): number {
  const canvas = tree.root.findByProps({ testID: "ewma-chart-canvas" });
  const opacity = flattenedStyle(canvas.props.style).opacity;
  // Mid-reveal the opacity is an Animated interpolation; resolve its current
  // value. Settled/armed it is a plain number.
  return typeof opacity === "number"
    ? opacity
    : (opacity as { __getValue: () => number }).__getValue();
}

describe("EWMATrendChart — draw-in (FTY-380)", () => {
  it("arms once on loading → data: stroke reveal mid-flight, then a resting render identical to the static chart", () => {
    autoFinishAnimations = false;
    const tree = render(chartWith([], [], true));
    expect(drawInTimings()).toHaveLength(0);

    act(() => tree.update(chartWith(ENTRIES, EWMA_KG)));
    expect(drawInTimings()).toHaveLength(1);

    // Mid-reveal: the trend line carries the stroke-reveal dash props and the
    // canvas is still fading in — but the geometry (points) is already final.
    const midLine = tree.root.findAllByType(Polyline)[0]!;
    expect(midLine.props.strokeDasharray).toBeDefined();
    expect(midLine.props.strokeDashoffset).toBeDefined();
    const midPoints = midLine.props.points as string;
    expect(canvasOpacity(tree)).toBe(0);

    // Complete the reveal: the resting render drops the dash props entirely and
    // the canvas is fully opaque — pixel-identical to the pre-FTY-380 chart.
    act(() => {
      pendingAnimations.shift()?.({ finished: true });
    });
    const settledLine = tree.root.findAllByType(Polyline)[0]!;
    expect(settledLine.props.strokeDasharray).toBeUndefined();
    expect(settledLine.props.strokeDashoffset).toBeUndefined();
    expect(settledLine.props.points).toBe(midPoints);
    expect(canvasOpacity(tree)).toBe(1);
    expect(trendCircles(tree)).toHaveLength(ENTRIES.length);
  });

  it("does not re-arm on an unrelated re-render with identical data", () => {
    const tree = render(chartWith(ENTRIES, EWMA_KG));
    expect(drawInTimings()).toHaveLength(1);

    // Fresh array/object identities, same content — a focus refetch returning
    // the same series, or any unrelated re-render.
    const cloned = ENTRIES.map((e) => ({ ...e }));
    act(() => tree.update(chartWith(cloned, computeEWMAFromEntries(cloned))));

    expect(drawInTimings()).toHaveLength(1);
    expect(canvasOpacity(tree)).toBe(1);
  });

  it("re-arms exactly once when the data set changes (a range change)", () => {
    const tree = render(chartWith(ENTRIES, EWMA_KG));
    expect(drawInTimings()).toHaveLength(1);

    act(() => tree.update(chartWith(MORE_ENTRIES, MORE_EWMA_KG)));
    expect(drawInTimings()).toHaveLength(2);
    expect(canvasOpacity(tree)).toBe(1);
  });

  it("re-arms when the settled range changes even if the series content is identical", () => {
    const tree = render(chartWith(ENTRIES, EWMA_KG, false, "1M"));
    expect(drawInTimings()).toHaveLength(1);

    // A 1M → 3M switch whose wider window holds no additional entries: the
    // refetch resolves the same content under the new settled range — still a
    // user-initiated data-settle, so the reveal replays once.
    act(() => tree.update(chartWith(ENTRIES, EWMA_KG, false, "3M")));
    expect(drawInTimings()).toHaveLength(2);
    expect(canvasOpacity(tree)).toBe(1);
  });

  it("renders instantly fully drawn under Reduce Motion — no reveal, no animated stroke offset", () => {
    mockReduceMotion(true);
    const tree = render(chartWith(ENTRIES, EWMA_KG));

    expect(timingSpy).not.toHaveBeenCalled();
    const line = tree.root.findAllByType(Polyline)[0]!;
    expect(line.props.strokeDasharray).toBeUndefined();
    expect(line.props.strokeDashoffset).toBeUndefined();
    expect(canvasOpacity(tree)).toBe(1);
  });
});

describe("EWMATrendChart — draw-in bounded Reduce-Motion wait (FTY-379 gate)", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    // The accessibility read never settles — the FTY-379 hazard.
    jest
      .spyOn(AccessibilityInfo, "isReduceMotionEnabled")
      .mockReturnValue(new Promise<boolean>(() => {}));
    jest
      .spyOn(AccessibilityInfo, "addEventListener")
      .mockReturnValue({ remove: jest.fn() } as never);
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("reveals with the no-motion fade after the bounded wait — never left suppressed", () => {
    const tree = render(chartWith(ENTRIES, EWMA_KG));

    // Armed but the setting is unknown: held hidden, nothing animating yet.
    expect(canvasOpacity(tree)).toBe(0);
    expect(timingSpy).not.toHaveBeenCalled();

    // Past the deadline the chart reveals with the no-motion fade (the short
    // reduced-motion duration), not the stroke sweep.
    act(() => {
      jest.advanceTimersByTime(400);
    });
    expect(drawInTimings()).toHaveLength(0);
    const fadeCalls = timingSpy.mock.calls.filter(
      ([, cfg]) => (cfg as { duration?: number }).duration === reducedMotionDuration,
    );
    expect(fadeCalls).toHaveLength(1);

    // The fade completes (FAKE_ANIM auto-finishes): settled, fully drawn.
    const line = tree.root.findAllByType(Polyline)[0]!;
    expect(line.props.strokeDasharray).toBeUndefined();
    expect(canvasOpacity(tree)).toBe(1);
  });
});

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
          today={TEST_TODAY}
          width={TEST_WIDTH}
        />,
      ),
    ).not.toThrow();
  });
});
