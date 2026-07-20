/**
 * Weigh-in reminder scheduling for FTY-101 (option set widened in FTY-403).
 *
 * Cadence, most → least frequent: Daily · Every other day · Twice a week ·
 * Weekly · Every 2 weeks · Monthly · Off. Default: Weekly.
 *
 * FTY-403 replaced the 4-segment `UISegmentedControl` with a native
 * menu/picker (`MenuPicker`), so labels no longer have to be short and
 * equal-width to dodge segment truncation (FTY-347): the menu lists each option
 * on its own full-width row. That frees the biweekly label to be the clearer
 * "Every 2 weeks" instead of the ambiguous "Biweekly", and lets the frequent
 * cadences carry their honest names. Only the `label` is cosmetic — `value` and
 * `days` are the contract surface the scheduler and persistence speak.
 *
 * The reminder is due-only: exactly one notification fires at
 * `last_weigh_in + cadence_interval`, and it is never a *repeating* system
 * notification. A sub-weekly cadence (daily / every-other-day / twice-weekly)
 * still schedules only that single due-shot, re-armed after each weigh-in — not
 * an OS repeat trigger. Logging a weight or changing the cadence reschedules
 * forward. "Off" cancels any pending reminder.
 *
 * The scheduling logic is split from the notification platform code via
 * injectable adapters (NotificationsAdapter, CadenceStore) so it is fully
 * unit-testable without expo-notifications or expo-file-system.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type WeighInCadence =
  | "daily"
  | "every-other-day"
  | "twice-weekly"
  | "weekly"
  | "biweekly"
  | "monthly"
  | "off";

export interface CadenceOption {
  readonly label: string;
  readonly value: WeighInCadence;
  /** Interval in days, or null for "off". */
  readonly days: number | null;
}

// Ordered most → least frequent, "Off" last (the ordinal order the menu shows).
// The three sub-weekly cadences carry whole-day intervals so the single
// due-shot lands cleanly at 09:00 (see computeNextDueDate). "Twice a week" maps
// to a 3-day interval — the closest whole-day spacing to two nudges a week.
export const CADENCE_OPTIONS: readonly CadenceOption[] = [
  { label: "Daily", value: "daily", days: 1 },
  { label: "Every other day", value: "every-other-day", days: 2 },
  { label: "Twice a week", value: "twice-weekly", days: 3 },
  { label: "Weekly", value: "weekly", days: 7 },
  { label: "Every 2 weeks", value: "biweekly", days: 14 },
  { label: "Monthly", value: "monthly", days: 30 },
  { label: "Off", value: "off", days: null },
];

export const DEFAULT_CADENCE: WeighInCadence = "weekly";

/** Returns the number of days for a cadence, or null for "off". */
export function cadenceIntervalDays(cadence: WeighInCadence): number | null {
  return CADENCE_OPTIONS.find((o) => o.value === cadence)!.days;
}

// ─────────────────────────────────────────────────────────────────────────────
// Pure scheduling computation
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Compute when the next weigh-in is due.
 * Returns null when cadence is 'off' or no last weigh-in date is known.
 * The due date fires at 09:00 local time.
 */
export function computeNextDueDate(
  lastWeighInDate: string | null,
  cadence: WeighInCadence,
): Date | null {
  const days = cadenceIntervalDays(cadence);
  if (days === null || lastWeighInDate === null) return null;
  const [y, m, d] = lastWeighInDate.split("-").map(Number);
  const due = new Date(y!, m! - 1, d!);
  due.setDate(due.getDate() + days);
  due.setHours(9, 0, 0, 0);
  return due;
}

// ─────────────────────────────────────────────────────────────────────────────
// Injectable adapters (implemented concretely in cadenceAdapter.ts)
// ─────────────────────────────────────────────────────────────────────────────

export interface NotificationsAdapter {
  /** Request permission. Returns true if granted. */
  requestPermission(): Promise<boolean>;
  /** Cancel all previously scheduled weigh-in reminders. */
  cancelAll(): Promise<void>;
  /**
   * Schedule exactly one notification at the given date.
   * The notification body must contain no weight or nutrition values.
   */
  scheduleAt(date: Date): Promise<void>;
}

export interface CadenceStore {
  getCadence(): Promise<WeighInCadence | null>;
  setCadence(cadence: WeighInCadence): Promise<void>;
  getLastWeighInDate(): Promise<string | null>;
  setLastWeighInDate(date: string): Promise<void>;
}

// ─────────────────────────────────────────────────────────────────────────────
// Scheduling operations
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Apply a cadence change: persist it and reschedule the reminder.
 *
 * - "Off": cancels any existing reminder.
 * - Permission denied: preference saved, no notification (degrades gracefully).
 * - No last weigh-in date: no notification scheduled until the first weigh-in.
 *
 * This schedules AT MOST ONE future notification. No daily or repeating
 * notifications are ever created.
 */
export async function applyReminderSettings(
  cadence: WeighInCadence,
  lastWeighInDate: string | null,
  store: CadenceStore,
  notifications: NotificationsAdapter,
): Promise<void> {
  await store.setCadence(cadence);

  if (cadence === "off") {
    await notifications.cancelAll();
    return;
  }

  const dueDate = computeNextDueDate(lastWeighInDate, cadence);
  if (dueDate === null) {
    // No last weigh-in to compute from — schedule will be set on first log.
    return;
  }

  const granted = await notifications.requestPermission();
  if (!granted) {
    // Degrade gracefully: preference saved, no notification fires.
    return;
  }

  // Cancel any existing reminder before scheduling the single new one.
  await notifications.cancelAll();
  await notifications.scheduleAt(dueDate);
}

/**
 * Called after a new weight entry is logged. Persists the weigh-in date and
 * reschedules the due-only reminder forward.
 */
export async function onWeightLogged(
  weighInDate: string,
  store: CadenceStore,
  notifications: NotificationsAdapter,
): Promise<void> {
  await store.setLastWeighInDate(weighInDate);
  const cadence = (await store.getCadence()) ?? DEFAULT_CADENCE;
  await applyReminderSettings(cadence, weighInDate, store, notifications);
}
