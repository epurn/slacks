/**
 * Trend computation for FTY-101: EWMA smoothing, date-range utilities,
 * and intake-adherence summarisation over the daily-summary series.
 *
 * All exports are pure, deterministic functions — testable without mocking.
 * The EWMA parameters and on-target tolerance are single documented constants.
 */

import type { WeightEntryDTO } from "@/api/weightEntries";
import type { DailySummaryDTO } from "@/api/dailySummary";
import type { UnitsPreference } from "@/state/profile";
import {
  kgToDisplay,
  weightUnitLabel,
  formatDate,
  subtractDays,
} from "@/state/weightEntries";

// ─────────────────────────────────────────────────────────────────────────────
// EWMA — Exponentially-Weighted Moving Average
//
// α = 0.2 is the established smoothing factor for daily body-weight series.
// Source: The Hacker's Diet by John Walker <https://www.fourmilab.ch/hackdiet/>
// Adopted by Trendweight / Libra-style apps: a one-day spike blunts the trend
// line rather than jerking it — exactly the "lead with the trend,
// de-emphasise any single reading" behaviour §4b requires.
//
// EWMA is preferred over a plain N-day SMA: SMA lags badly and reacts hard
// when a single outlier enters or leaves the window.
//
// Seeding rule: EWMA[0] = weight[0] (the first reading, not a warm-up value).
// This ensures sparse and early ranges render without a startup artifact — the
// smoothed line begins at the first known value and naturally converges to the
// true trend as more readings arrive.
// ─────────────────────────────────────────────────────────────────────────────

/** EWMA smoothing factor. See the module comment for justification. */
export const EWMA_ALPHA = 0.2;

/**
 * Compute the EWMA trend over a series of weight values.
 * Input and output are in the same units, oldest-first.
 * Empty → []. Single element → [element] (seeded, no startup artifact).
 */
export function computeEWMA(weights: readonly number[]): number[] {
  if (weights.length === 0) return [];
  const result: number[] = [weights[0]!];
  for (let i = 1; i < weights.length; i++) {
    result.push(EWMA_ALPHA * weights[i]! + (1 - EWMA_ALPHA) * result[i - 1]!);
  }
  return result;
}

// ─────────────────────────────────────────────────────────────────────────────
// Date ranges
// ─────────────────────────────────────────────────────────────────────────────

export type DateRangeKey = "1M" | "3M" | "6M";

export interface DateRangeOption {
  readonly key: DateRangeKey;
  readonly label: string;
  readonly days: number;
}

/** Configurable range list — add new options here without a contract change. */
export const DATE_RANGE_OPTIONS: readonly DateRangeOption[] = [
  { key: "1M", label: "1M", days: 30 },
  { key: "3M", label: "3M", days: 90 },
  { key: "6M", label: "6M", days: 180 },
];

export const DEFAULT_DATE_RANGE: DateRangeKey = "1M";

export function rangeDays(key: DateRangeKey): number {
  return DATE_RANGE_OPTIONS.find((r) => r.key === key)!.days;
}

/** Compute the from/to date strings for a range, relative to today. */
export function rangeBounds(
  range: DateRangeKey,
  today: Date,
): { from: string; to: string } {
  return {
    from: formatDate(subtractDays(today, rangeDays(range))),
    to: formatDate(today),
  };
}

/**
 * Build an array of YYYY-MM-DD strings for every calendar day from
 * `from` through `to` inclusive (oldest first).
 */
export function buildDayRange(from: string, to: string): string[] {
  const result: string[] = [];
  const [fy, fm, fd] = from.split("-").map(Number);
  const [ty, tm, td] = to.split("-").map(Number);
  const cur = new Date(fy!, fm! - 1, fd!);
  const end = new Date(ty!, tm! - 1, td!);
  while (cur <= end) {
    result.push(formatDate(cur));
    cur.setDate(cur.getDate() + 1);
  }
  return result;
}

// ─────────────────────────────────────────────────────────────────────────────
// Headline delta
// ─────────────────────────────────────────────────────────────────────────────

export interface HeadlineDelta {
  /** Current smoothed value in display units (last EWMA value). */
  readonly current: number;
  /** Signed change across the range (current − start), in display units. */
  readonly delta: number;
  /** Unit label, e.g. "kg" or "lb". */
  readonly unit: string;
  /** Direction arrow character for display. */
  readonly direction: "↑" | "↓" | "→";
}

/**
 * Compute the headline delta from the EWMA trend (in canonical kg).
 * Returns null when there are no entries.
 */
export function computeHeadlineDelta(
  ewmaKg: readonly number[],
  unitsPreference: UnitsPreference,
): HeadlineDelta | null {
  if (ewmaKg.length === 0) return null;
  const unit = weightUnitLabel(unitsPreference);
  const currentKg = ewmaKg[ewmaKg.length - 1]!;
  const startKg = ewmaKg[0]!;
  const current = kgToDisplay(currentKg, unitsPreference);
  const start = kgToDisplay(startKg, unitsPreference);
  // Round to 1 decimal to match display precision.
  const delta = Math.round((current - start) * 10) / 10;
  const direction: "↑" | "↓" | "→" =
    delta > 0.05 ? "↑" : delta < -0.05 ? "↓" : "→";
  return { current, delta, unit, direction };
}

/**
 * Compute EWMA values in canonical kg from a weight-entry series.
 * Input: weight entries ordered oldest-first (FTY-070 list-range order).
 */
export function computeEWMAFromEntries(
  entries: readonly WeightEntryDTO[],
): number[] {
  return computeEWMA(entries.map((e) => e.weight_kg));
}

// ─────────────────────────────────────────────────────────────────────────────
// Intake adherence
// ─────────────────────────────────────────────────────────────────────────────

/**
 * On-target tolerance: intake within ±10% of target calories qualifies.
 * Defined once so the strip, counter, and tests all use the same rule.
 */
export const ON_TARGET_TOLERANCE = 0.1;

export type AdherenceDayState =
  | "on-target"
  | "off-target"
  | "no-target"
  | "no-data";

export interface AdherenceDay {
  readonly date: string;
  readonly state: AdherenceDayState;
  readonly intakeCalories: number | null;
  readonly targetCalories: number | null;
}

export interface AdherenceSummary {
  readonly days: readonly AdherenceDay[];
  /** Average kcal across days that have intake data. null when none. */
  readonly avgCalories: number | null;
  /** Count of days classified as on-target. */
  readonly daysOnTarget: number;
  /**
   * Count of days that have a target (on-target + off-target).
   * Null-target days are excluded from this denominator per the contract.
   */
  readonly daysWithTarget: number;
}

/**
 * Classify one day's adherence from its daily-summary DTO.
 * An unlogged day (`has_intake` false) → 'no-data': its zeroed intake is not a
 * real 0-kcal reading, so it must not land in the average or the on/off-target
 * denominator. A null target → 'no-target' (excluded from the denominator, not a
 * miss).
 */
export function dayAdherenceState(summary: DailySummaryDTO): AdherenceDayState {
  if (!summary.has_intake) return "no-data";
  if (summary.target === null) return "no-target";
  const target = summary.target.calories.effective;
  const intake = summary.intake.calories;
  const lower = target * (1 - ON_TARGET_TOLERANCE);
  const upper = target * (1 + ON_TARGET_TOLERANCE);
  return intake >= lower && intake <= upper ? "on-target" : "off-target";
}

/**
 * Summarise adherence for a date range.
 * `summaries` entries may be null (fetch failed for that day).
 * `allDates` is the full ordered list of expected dates (oldest-first).
 * Days are rendered as 'no-data' — and excluded from the average and the
 * on/off-target denominator — when they are absent/null from `summaries` (fetch
 * gap) OR present but unlogged (`has_intake` false); the range endpoint returns
 * every calendar day, so in production the unlogged case is the real one. Only a
 * genuinely logged day (which may carry a true 0-kcal intake) counts.
 */
export function computeAdherence(
  summaries: readonly (DailySummaryDTO | null)[],
  allDates: readonly string[],
): AdherenceSummary {
  const byDate = new Map<string, DailySummaryDTO>();
  for (const s of summaries) {
    if (s !== null) byDate.set(s.date, s);
  }

  const days: AdherenceDay[] = allDates.map((date) => {
    const s = byDate.get(date);
    const state = s ? dayAdherenceState(s) : ("no-data" as const);
    if (!s || state === "no-data") {
      return {
        date,
        state: "no-data" as const,
        intakeCalories: null,
        targetCalories: null,
      };
    }
    return {
      date,
      state,
      intakeCalories: s.intake.calories,
      targetCalories: s.target?.calories.effective ?? null,
    };
  });

  const withIntake = days.filter((d) => d.state !== "no-data");
  const avgCalories =
    withIntake.length > 0
      ? Math.round(
          withIntake.reduce((sum, d) => sum + (d.intakeCalories ?? 0), 0) /
            withIntake.length,
        )
      : null;

  const daysOnTarget = days.filter((d) => d.state === "on-target").length;
  const daysWithTarget = days.filter(
    (d) => d.state === "on-target" || d.state === "off-target",
  ).length;

  return { days, avgCalories, daysOnTarget, daysWithTarget };
}
