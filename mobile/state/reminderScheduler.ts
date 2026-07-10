/**
 * Weigh-in reminder scheduling for FTY-101.
 *
 * Cadence: Weekly · Biweekly · Monthly · Off. Default: Weekly.
 *
 * The display labels are kept short and equal-length-ish so the four segments
 * fit the native equal-width `UISegmentedControl` without ellipsis on the
 * narrowest supported phone (FTY-347). "Biweekly" sits between Weekly and
 * Monthly, which disambiguates it as *every two weeks*. Only the `label` is
 * cosmetic — `value` and `days` are the contract surface and never change.
 *
 * The reminder is due-only: exactly one notification fires at
 * `last_weigh_in + cadence_interval`. It is never a daily or repeating
 * notification. Logging a weight or changing the cadence reschedules forward.
 * "Off" cancels any pending reminder.
 *
 * The scheduling logic is split from the notification platform code via
 * injectable adapters (NotificationsAdapter, CadenceStore) so it is fully
 * unit-testable without expo-notifications or expo-file-system.
 */

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────

export type WeighInCadence = "weekly" | "biweekly" | "monthly" | "off";

export interface CadenceOption {
  readonly label: string;
  readonly value: WeighInCadence;
  /** Interval in days, or null for "off". */
  readonly days: number | null;
}

export const CADENCE_OPTIONS: readonly CadenceOption[] = [
  { label: "Weekly", value: "weekly", days: 7 },
  { label: "Biweekly", value: "biweekly", days: 14 },
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
