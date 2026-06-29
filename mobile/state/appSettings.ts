/**
 * On-device preferences for appearance (Light / Dark / System).
 *
 * Stored as a JSON file via expo-file-system (non-sensitive display preference).
 * The cadence preference lives alongside in the FileCadenceStore; appearance is
 * separate so the ThemeProvider can read it independently on boot.
 *
 * The seam is injectable so the SettingsScreen tests can drive it without the
 * platform filesystem.
 */

import { File, Paths } from 'expo-file-system';

import type { ColorSchemeOverride } from '@/theme';

/** Persistence seam for the on-device appearance override. */
export interface AppSettingsStore {
  getAppearance(): Promise<ColorSchemeOverride>;
  setAppearance(v: ColorSchemeOverride): Promise<void>;
}

interface StoredAppSettings {
  appearance?: ColorSchemeOverride;
}

const VALID_APPEARANCES = new Set<string>(['light', 'dark', 'system']);

function isColorSchemeOverride(v: unknown): v is ColorSchemeOverride {
  return typeof v === 'string' && VALID_APPEARANCES.has(v);
}

function getSettingsFile(): File {
  return new File(Paths.document, 'fatty-app-settings.json');
}

async function readStored(): Promise<StoredAppSettings> {
  try {
    const file = getSettingsFile();
    if (!file.exists) return {};
    const raw = await file.text();
    return JSON.parse(raw) as StoredAppSettings;
  } catch {
    return {};
  }
}

function writeStored(data: StoredAppSettings): void {
  const file = getSettingsFile();
  file.write(JSON.stringify(data));
}

/** File-based on-device settings store backed by expo-file-system. */
export const fileAppSettingsStore: AppSettingsStore = {
  async getAppearance(): Promise<ColorSchemeOverride> {
    const data = await readStored();
    const v = data.appearance;
    return isColorSchemeOverride(v) ? v : 'system';
  },

  async setAppearance(v: ColorSchemeOverride): Promise<void> {
    const data = await readStored();
    writeStored({ ...data, appearance: v });
  },
};
