/**
 * Weight-entry display utilities: unit conversion and input parsing.
 *
 * FTY-070's backend stores and returns all weights in canonical kilograms.
 * The POST request accepts `weight` in the user's `units_preference` (kg for
 * metric, lb for imperial) — the backend converts on write. GET responses
 * always return `weight_kg` in canonical kg; this module converts those values
 * to display units for the chart and input labels.
 *
 * The lb/kg conversion factor matches `state/profile.ts` (NIST definition).
 */

import type { UnitsPreference } from "@/state/profile";
export type { UnitsPreference };

const KG_PER_LB = 0.45359237;

function round(value: number, decimals: number): number {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

/** Display label for the user's weight unit. */
export function weightUnitLabel(units: UnitsPreference): string {
  return units === "metric" ? "kg" : "lb";
}

/** Convert a canonical kg value to display units, rounded to 1 decimal. */
export function kgToDisplay(kg: number, units: UnitsPreference): number {
  return units === "metric" ? round(kg, 1) : round(kg / KG_PER_LB, 1);
}

/**
 * Parse a user-entered weight string. Returns null if the input is empty,
 * non-numeric, or not strictly positive.
 */
export function parseWeightInput(text: string): number | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const value = Number(trimmed);
  return Number.isFinite(value) && value > 0 ? value : null;
}

/** Format a Date as a YYYY-MM-DD string for use as an API `effective_date`. */
export function formatDate(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** Return a new Date that is `days` calendar days before `from`. */
export function subtractDays(from: Date, days: number): Date {
  const result = new Date(from.getTime());
  result.setDate(result.getDate() - days);
  return result;
}

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
] as const;

/**
 * Human-format a `YYYY-MM-DD` calendar date for user-facing display: "Today" /
 * "Yesterday" relative to `todayStr` (also `YYYY-MM-DD`), else "{Month} {Day}"
 * (e.g. "June 1", no year — Trends ranges never span more than six months).
 *
 * Deliberately avoids `toLocaleDateString`/`Intl.DateTimeFormat` for this: both
 * dates are already resolved calendar days (no timezone left to apply), and a
 * plain lookup sidesteps the Hermes locale bugs `formatWallClockTime`
 * (state/today.ts) works around for wall-clock time. Machine date strings (DTO
 * fields, testIDs) stay ISO — this is presentation only.
 */
export function formatHumanDate(dateStr: string, todayStr: string): string {
  if (dateStr === todayStr) return "Today";

  const [y, m, d] = dateStr.split("-").map(Number);
  const [ty, tm, td] = todayStr.split("-").map(Number);
  const date = new Date(y!, m! - 1, d!);
  const yesterday = new Date(ty!, tm! - 1, td!);
  yesterday.setDate(yesterday.getDate() - 1);

  if (
    date.getFullYear() === yesterday.getFullYear() &&
    date.getMonth() === yesterday.getMonth() &&
    date.getDate() === yesterday.getDate()
  ) {
    return "Yesterday";
  }

  return `${MONTH_NAMES[m! - 1]} ${d}`;
}
