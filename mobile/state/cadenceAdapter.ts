/**
 * Concrete adapter implementations for FTY-101 weigh-in reminder scheduling.
 *
 * ExpoNotificationsAdapter — wraps expo-notifications for due-only reminders.
 * FileCadenceStore — persists the cadence preference using expo-file-system
 *   (SDK 56 File/Paths API).
 *
 * These are separated from reminderScheduler.ts so tests can inject mocks
 * without needing platform APIs.
 */

import { File, Paths } from "expo-file-system";
import * as Notifications from "expo-notifications";
import { SchedulableTriggerInputTypes } from "expo-notifications";

import type {
  CadenceStore,
  NotificationsAdapter,
  WeighInCadence,
} from "@/state/reminderScheduler";

// ─────────────────────────────────────────────────────────────────────────────
// ExpoNotificationsAdapter
// ─────────────────────────────────────────────────────────────────────────────

/** Notification copy — no weight values or numbers per security requirement. */
const NOTIFICATION_CONTENT = {
  title: "Time to weigh in",
  body: "Log your weight to keep your trend on track.",
} as const;

export const expoNotificationsAdapter: NotificationsAdapter = {
  async requestPermission(): Promise<boolean> {
    const { status } = await Notifications.requestPermissionsAsync();
    return status === "granted";
  },

  async cancelAll(): Promise<void> {
    await Notifications.cancelAllScheduledNotificationsAsync();
  },

  async scheduleAt(date: Date): Promise<void> {
    await Notifications.scheduleNotificationAsync({
      content: NOTIFICATION_CONTENT,
      trigger: {
        type: SchedulableTriggerInputTypes.DATE,
        date,
      },
    });
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// FileCadenceStore
// ─────────────────────────────────────────────────────────────────────────────

function getCadenceFile(): File {
  return new File(Paths.document, "slacks-cadence.json");
}

interface StoredCadenceData {
  cadence?: WeighInCadence;
  lastWeighInDate?: string;
}

async function readStored(): Promise<StoredCadenceData> {
  try {
    const file = getCadenceFile();
    if (!file.exists) return {};
    const raw = await file.text();
    return JSON.parse(raw) as StoredCadenceData;
  } catch {
    return {};
  }
}

function writeStored(data: StoredCadenceData): void {
  const file = getCadenceFile();
  file.write(JSON.stringify(data));
}

export const fileCadenceStore: CadenceStore = {
  async getCadence(): Promise<WeighInCadence | null> {
    const data = await readStored();
    return data.cadence ?? null;
  },

  async setCadence(cadence: WeighInCadence): Promise<void> {
    const data = await readStored();
    writeStored({ ...data, cadence });
  },

  async getLastWeighInDate(): Promise<string | null> {
    const data = await readStored();
    return data.lastWeighInDate ?? null;
  },

  async setLastWeighInDate(date: string): Promise<void> {
    const data = await readStored();
    writeStored({ ...data, lastWeighInDate: date });
  },
};
