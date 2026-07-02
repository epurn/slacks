import type { WeightEntryDTO } from "@/api/weightEntries";
import type { DailySummaryDTO, TargetReadModel } from "@/api/dailySummary";
import {
  EWMA_ALPHA,
  computeEWMA,
  computeEWMAFromEntries,
  computeHeadlineDelta,
  computeAdherence,
  dayAdherenceState,
  ON_TARGET_TOLERANCE,
  DATE_RANGE_OPTIONS,
  DEFAULT_DATE_RANGE,
  DEFAULT_GOAL_DIRECTION,
  rangeDays,
  rangeBounds,
  rangeProse,
  resolveDeltaGoalState,
  buildDayRange,
} from "./trends";

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function entry(weight_kg: number, date: string): WeightEntryDTO {
  return {
    id: `id-${date}`,
    user_id: "uid",
    weight_kg,
    effective_date: date,
    created_at: `${date}T08:00:00Z`,
    updated_at: `${date}T08:00:00Z`,
  };
}

function makeTarget(calories: number): TargetReadModel {
  return {
    calories: { effective: calories, derived: calories, source: "derived" },
    protein_g: { effective: 128, derived: 128, source: "derived" },
    carbs_g: { effective: 148, derived: 148, source: "derived" },
    fat_g: { effective: 64, derived: 64, source: "derived" },
  };
}

function summary(
  date: string,
  intake: number,
  targetCalories: number | null,
  hasIntake = true,
): DailySummaryDTO {
  return {
    date,
    intake: { calories: intake, protein_g: 80, carbs_g: 150, fat_g: 40 },
    has_intake: hasIntake,
    target: targetCalories !== null ? makeTarget(targetCalories) : null,
    exercise: { active_calories: 0 },
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// EWMA
// ─────────────────────────────────────────────────────────────────────────────

describe("computeEWMA", () => {
  it("returns [] for empty input", () => {
    expect(computeEWMA([])).toEqual([]);
  });

  it("returns [first] for a single element (seeded, no startup artifact)", () => {
    expect(computeEWMA([75])).toEqual([75]);
  });

  it("applies α=0.2: EWMA[1] = 0.2 * w[1] + 0.8 * EWMA[0]", () => {
    const result = computeEWMA([70, 80]);
    expect(result[0]).toBe(70);
    // 0.2 * 80 + 0.8 * 70 = 16 + 56 = 72
    expect(result[1]).toBeCloseTo(72, 5);
  });

  it("output length equals input length", () => {
    const weights = [70, 71, 69, 72, 70];
    expect(computeEWMA(weights)).toHaveLength(weights.length);
  });

  it("a one-day spike does NOT swing the trend line (core 'encourage the trend' property)", () => {
    // Day 1-4 stable at 70 kg, day 5 spike to 80 kg, day 6 back to 70.
    const weights = [70, 70, 70, 70, 80, 70];
    const ewma = computeEWMA(weights);
    // After spike: EWMA[4] = 0.2*80 + 0.8*EWMA[3]
    // EWMA[3] stays close to 70 (all 70s before).
    // EWMA[4] = 0.2*80 + 0.8*70 = 72 — well below the raw 80
    expect(ewma[4]).toBeLessThan(75);
    expect(ewma[4]).toBeGreaterThan(70);
    // EWMA[5] recovers quickly back toward 70
    expect(ewma[5]).toBeLessThan(ewma[4]!);
  });

  it("sparse series (single point) renders without artifact", () => {
    const result = computeEWMA([82.3]);
    expect(result).toHaveLength(1);
    expect(result[0]).toBe(82.3);
  });

  it("produces a deterministic, snapshot-stable trend over a noisy series", () => {
    // Reference series from the Hacker's Diet example.
    const weights = [75, 74.5, 76, 73.5, 75.5, 74, 73, 74.5, 72, 73];
    const ewma = computeEWMA(weights);
    // First value is seeded from first weight
    expect(ewma[0]).toBe(75);
    // All values are finite numbers
    for (const v of ewma) {
      expect(Number.isFinite(v)).toBe(true);
    }
    // The EWMA trend should be smoother than the raw series:
    // check that the range of EWMA is smaller than range of raw
    const rawRange = Math.max(...weights) - Math.min(...weights);
    const ewmaRange = Math.max(...ewma) - Math.min(...ewma);
    expect(ewmaRange).toBeLessThan(rawRange);
  });
});

describe("EWMA_ALPHA", () => {
  it("is 0.2 (the documented smoothing factor)", () => {
    expect(EWMA_ALPHA).toBe(0.2);
  });
});

describe("computeEWMAFromEntries", () => {
  it("extracts weight_kg values and applies EWMA", () => {
    const entries = [entry(70, "2026-06-01"), entry(72, "2026-06-10")];
    const result = computeEWMAFromEntries(entries);
    expect(result[0]).toBe(70);
    // 0.2 * 72 + 0.8 * 70 = 70.4
    expect(result[1]).toBeCloseTo(70.4, 5);
  });

  it("returns [] for empty entries", () => {
    expect(computeEWMAFromEntries([])).toEqual([]);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Date ranges
// ─────────────────────────────────────────────────────────────────────────────

describe("DATE_RANGE_OPTIONS", () => {
  it("contains 1M, 3M, 6M options", () => {
    const keys = DATE_RANGE_OPTIONS.map((o) => o.key);
    expect(keys).toContain("1M");
    expect(keys).toContain("3M");
    expect(keys).toContain("6M");
  });

  it("never exposes a raw range key in a visible or spoken label (FTY-189)", () => {
    for (const opt of DATE_RANGE_OPTIONS) {
      expect(opt.label).not.toMatch(/\b[136]M\b/);
      expect(opt.accessibilityLabel).not.toMatch(/\b[136]M\b/);
    }
  });
});

describe("DEFAULT_DATE_RANGE", () => {
  it("is '1M'", () => {
    expect(DEFAULT_DATE_RANGE).toBe("1M");
  });
});

describe("rangeDays", () => {
  it("returns 30 for 1M", () => expect(rangeDays("1M")).toBe(30));
  it("returns 90 for 3M", () => expect(rangeDays("3M")).toBe(90));
  it("returns 180 for 6M", () => expect(rangeDays("6M")).toBe(180));
});

describe("rangeBounds", () => {
  it("computes correct from/to for 1M range", () => {
    const today = new Date(2026, 5, 27); // June 27, local time
    const { from, to } = rangeBounds("1M", today);
    expect(to).toBe("2026-06-27");
    expect(from).toBe("2026-05-28");
  });
});

describe("buildDayRange", () => {
  it("builds a range inclusive of both endpoints", () => {
    const days = buildDayRange("2026-06-01", "2026-06-03");
    expect(days).toEqual(["2026-06-01", "2026-06-02", "2026-06-03"]);
  });

  it("returns a single-element array for same from/to", () => {
    expect(buildDayRange("2026-06-27", "2026-06-27")).toEqual(["2026-06-27"]);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Headline delta
// ─────────────────────────────────────────────────────────────────────────────

describe("computeHeadlineDelta", () => {
  it("returns null for an empty EWMA array", () => {
    expect(computeHeadlineDelta([], "metric")).toBeNull();
  });

  it("returns current = first value and delta = 0 for a single entry", () => {
    const result = computeHeadlineDelta([70], "metric");
    expect(result).not.toBeNull();
    expect(result!.current).toBe(70);
    expect(result!.delta).toBe(0);
    expect(result!.direction).toBe("→");
  });

  it("computes delta as last − first in the user's display units (metric)", () => {
    const result = computeHeadlineDelta([70, 68.5], "metric");
    expect(result!.current).toBeCloseTo(68.5, 1);
    expect(result!.delta).toBeCloseTo(-1.5, 1);
    expect(result!.unit).toBe("kg");
    expect(result!.direction).toBe("↓");
  });

  it("converts to lb for imperial users", () => {
    // 70 kg ≈ 154.3 lb; 69 kg ≈ 152.1 lb
    const result = computeHeadlineDelta([70, 69], "imperial");
    expect(result!.unit).toBe("lb");
    expect(result!.current).toBeGreaterThan(150);
    expect(result!.delta).toBeLessThan(0);
    expect(result!.direction).toBe("↓");
  });

  it("shows ↑ for an increasing trend", () => {
    const result = computeHeadlineDelta([70, 72], "metric");
    expect(result!.direction).toBe("↑");
  });

  it("shows → for a flat trend (within rounding tolerance)", () => {
    const result = computeHeadlineDelta([70.01, 70.03], "metric");
    expect(result!.direction).toBe("→");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Adherence
// ─────────────────────────────────────────────────────────────────────────────

describe("ON_TARGET_TOLERANCE", () => {
  it("is 10%", () => {
    expect(ON_TARGET_TOLERANCE).toBe(0.1);
  });
});

describe("dayAdherenceState", () => {
  it("returns 'no-target' when target is null", () => {
    expect(dayAdherenceState(summary("2026-06-01", 1800, null))).toBe(
      "no-target",
    );
  });

  it("returns 'on-target' when intake is within ±10% of target", () => {
    // Target 2000 → [1800, 2200] is on-target band.
    expect(dayAdherenceState(summary("2026-06-01", 1800, 2000))).toBe(
      "on-target",
    );
    expect(dayAdherenceState(summary("2026-06-01", 2000, 2000))).toBe(
      "on-target",
    );
    expect(dayAdherenceState(summary("2026-06-01", 2200, 2000))).toBe(
      "on-target",
    );
  });

  it("returns 'off-target' when intake is outside ±10% of target", () => {
    expect(dayAdherenceState(summary("2026-06-01", 1799, 2000))).toBe(
      "off-target",
    );
    expect(dayAdherenceState(summary("2026-06-01", 2201, 2000))).toBe(
      "off-target",
    );
  });

  it("returns 'no-data' for an unlogged day (has_intake false) even with a target", () => {
    // The range path returns unlogged days with a zeroed intake and has_intake
    // false — they must not be classed as an off-target miss.
    expect(dayAdherenceState(summary("2026-06-01", 0, 2000, false))).toBe(
      "no-data",
    );
  });

  it("a genuine 0-kcal logged day (has_intake true) is still classified against target", () => {
    expect(dayAdherenceState(summary("2026-06-01", 0, 2000, true))).toBe(
      "off-target",
    );
  });
});

describe("computeAdherence", () => {
  const allDates = ["2026-06-01", "2026-06-02", "2026-06-03"];

  it("counts on-target days correctly", () => {
    const summaries = [
      summary("2026-06-01", 2000, 2000), // on-target
      summary("2026-06-02", 1200, 2000), // off-target
      summary("2026-06-03", 2000, 2000), // on-target
    ];
    const result = computeAdherence(summaries, allDates);
    expect(result.daysOnTarget).toBe(2);
    expect(result.daysWithTarget).toBe(3);
  });

  it("null-target days are 'no-target', excluded from denominator, NOT counted as a miss", () => {
    const summaries = [
      summary("2026-06-01", 2000, 2000), // on-target
      summary("2026-06-02", 0, null),    // null target → no-target
      summary("2026-06-03", 1200, 2000), // off-target
    ];
    const result = computeAdherence(summaries, allDates);
    expect(result.days[1]!.state).toBe("no-target");
    // denominator excludes null-target day
    expect(result.daysWithTarget).toBe(2);
    // null-target day not counted as a miss
    expect(result.daysOnTarget).toBe(1);
  });

  it("missing days (null in summaries) render as 'no-data'", () => {
    const summaries = [
      summary("2026-06-01", 2000, 2000),
      null,
      summary("2026-06-03", 2000, 2000),
    ];
    const result = computeAdherence(summaries, allDates);
    expect(result.days[1]!.state).toBe("no-data");
    expect(result.days[0]!.state).toBe("on-target");
  });

  it("computes avg calories over days with intake data", () => {
    const summaries = [
      summary("2026-06-01", 1800, 2000),
      summary("2026-06-02", 2200, 2000),
      null,
    ];
    const result = computeAdherence(summaries, allDates);
    expect(result.avgCalories).toBe(2000); // (1800+2200)/2
  });

  it("excludes unlogged days from the average — a zeroed day from the range path is not a real 0-kcal day", () => {
    // The range endpoint returns EVERY calendar day, with intake zeroed and
    // has_intake false for days the user never logged (no literal null appears in
    // production). Counting those as real 0-kcal days drags the average down.
    const summaries = [
      summary("2026-06-01", 1800, 2000), // logged
      summary("2026-06-02", 0, 2000, false), // unlogged — zeroed by the range path
      summary("2026-06-03", 2200, 2000), // logged
    ];
    const result = computeAdherence(summaries, allDates);
    expect(result.days[1]!.state).toBe("no-data");
    expect(result.days[1]!.intakeCalories).toBeNull();
    expect(result.avgCalories).toBe(2000); // (1800+2200)/2 — zeroed day excluded
  });

  it("unlogged-but-targeted days are excluded from the on-target denominator, not counted as misses", () => {
    const summaries = [
      summary("2026-06-01", 2000, 2000), // on-target
      summary("2026-06-02", 0, 2000, false), // unlogged, has a target
      summary("2026-06-03", 0, 2000, false), // unlogged, has a target
    ];
    const result = computeAdherence(summaries, allDates);
    expect(result.daysOnTarget).toBe(1);
    expect(result.daysWithTarget).toBe(1); // unlogged-but-targeted days excluded
  });

  it("a genuine 0-kcal logged day (has_intake true) IS counted in the average and denominator", () => {
    const summaries = [
      summary("2026-06-01", 0, 2000, true), // logged a real 0 (e.g. water-only day)
      summary("2026-06-02", 0, 2000, true),
      summary("2026-06-03", 0, 2000, true),
    ];
    const result = computeAdherence(summaries, allDates);
    expect(result.avgCalories).toBe(0); // genuine zeros count
    expect(result.daysWithTarget).toBe(3);
    expect(result.daysOnTarget).toBe(0); // 0 vs 2000 → all off-target
  });

  it("returns null avgCalories when no summaries", () => {
    const result = computeAdherence([null, null, null], allDates);
    expect(result.avgCalories).toBeNull();
    expect(result.daysOnTarget).toBe(0);
    expect(result.daysWithTarget).toBe(0);
  });

  it("days array length equals allDates length", () => {
    const result = computeAdherence([], allDates);
    expect(result.days).toHaveLength(allDates.length);
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Range prose (FTY-189)
// ─────────────────────────────────────────────────────────────────────────────

describe("rangeProse", () => {
  it("maps 1M to 'this month'", () => {
    expect(rangeProse("1M")).toBe("this month");
  });

  it("maps 3M to 'these three months'", () => {
    expect(rangeProse("3M")).toBe("these three months");
  });

  it("maps 6M to 'these six months'", () => {
    expect(rangeProse("6M")).toBe("these six months");
  });

  it("never contains a raw range key for any option", () => {
    for (const opt of DATE_RANGE_OPTIONS) {
      const prose = rangeProse(opt.key);
      expect(prose).not.toMatch(/\b[136]M\b/);
    }
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Goal-aware delta state (FTY-189)
// ─────────────────────────────────────────────────────────────────────────────

describe("resolveDeltaGoalState", () => {
  it("a stable trend ('→') is always neutral, regardless of goal", () => {
    expect(resolveDeltaGoalState("→", "loss")).toBe("neutral");
    expect(resolveDeltaGoalState("→", "gain")).toBe("neutral");
    expect(resolveDeltaGoalState("→", "maintain")).toBe("neutral");
  });

  it("loss goal: a decrease is toward, an increase is away", () => {
    expect(resolveDeltaGoalState("↓", "loss")).toBe("toward");
    expect(resolveDeltaGoalState("↑", "loss")).toBe("away");
  });

  it("gain goal: an increase is toward, a decrease is away", () => {
    expect(resolveDeltaGoalState("↑", "gain")).toBe("toward");
    expect(resolveDeltaGoalState("↓", "gain")).toBe("away");
  });

  it("maintain goal: any real drift (up or down) is away", () => {
    expect(resolveDeltaGoalState("↑", "maintain")).toBe("away");
    expect(resolveDeltaGoalState("↓", "maintain")).toBe("away");
  });

  it("DEFAULT_GOAL_DIRECTION preserves the pre-FTY-189 'down = good' default", () => {
    expect(DEFAULT_GOAL_DIRECTION).toBe("loss");
    expect(resolveDeltaGoalState("↓", DEFAULT_GOAL_DIRECTION)).toBe("toward");
    expect(resolveDeltaGoalState("↑", DEFAULT_GOAL_DIRECTION)).toBe("away");
  });
});
