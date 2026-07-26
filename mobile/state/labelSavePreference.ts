/**
 * Sticky "save label photos" capture preference (FTY-433).
 *
 * The label flow used to ask "Save this photo?" on every single capture, on the
 * hot path between the shutter and the upload. That question is now a **sticky,
 * default-off preference** owned by the capture surface: it is read at shutter
 * time and sent as the `?save=` retention flag on the auto-upload
 * (`docs/contracts/label-upload.md`).
 *
 * Security / privacy: discard-by-default (FTY-077) is a hard invariant, so this
 * preference **fails closed**. Its default is `false`, an unreadable/corrupt
 * store reads as `false`, and consumers see `false` until the async hydrate
 * lands — a capture can therefore never upload with `save=true` unless the user
 * deliberately turned saving on. Nothing about the preference reaches the
 * network beyond the existing `?save=` flag, and no image data is stored here.
 *
 * The value is device-local, non-sensitive, and persisted as a JSON file via
 * expo-file-system — the same shape as the appearance store
 * (`state/appSettings.ts`), in its own file so the two can't clobber each
 * other's read-modify-write. The store is injectable so the capture screen's
 * tests can drive it without the platform filesystem.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { File, Paths } from "expo-file-system";

/** Persistence seam for the sticky save-label-photos preference. */
export interface LabelSavePreferenceStore {
  /** The stored preference; `false` (discard by default) when unset. */
  get(): Promise<boolean>;
  /** Persist the preference. */
  set(value: boolean): Promise<void>;
}

interface StoredCapturePreferences {
  saveLabelPhotos?: boolean;
}

/** Discard-by-default (FTY-077): saving is off until the user turns it on. */
export const DEFAULT_SAVE_LABEL_PHOTOS = false;

function getPreferencesFile(): File {
  return new File(Paths.document, "slacks-capture-preferences.json");
}

async function readStored(): Promise<StoredCapturePreferences> {
  try {
    const file = getPreferencesFile();
    if (!file.exists) return {};
    const raw = await file.text();
    return JSON.parse(raw) as StoredCapturePreferences;
  } catch {
    // Unreadable or corrupt: fail closed to the discard-by-default value.
    return {};
  }
}

/** File-based on-device capture-preferences store backed by expo-file-system. */
export const fileLabelSavePreferenceStore: LabelSavePreferenceStore = {
  async get(): Promise<boolean> {
    const data = await readStored();
    // Only a literal `true` enables retention — any other stored shape (missing,
    // null, a string, a corrupt file) reads as discard-by-default.
    return data.saveLabelPhotos === true;
  },

  async set(value: boolean): Promise<void> {
    const data = await readStored();
    getPreferencesFile().write(
      JSON.stringify({ ...data, saveLabelPhotos: value }),
    );
  },
};

/** The sticky preference plus its setter, as the capture chrome consumes it. */
export interface LabelSavePreference {
  /** Whether captures should ask the backend to retain the photo. */
  readonly saveLabelPhotos: boolean;
  /** Flip the preference; the new value sticks across launches. */
  setSaveLabelPhotos(next: boolean): void;
}

/**
 * Read + write the sticky save-label-photos preference.
 *
 * Starts at the discard-by-default value and hydrates from the store on mount,
 * so a shutter tap that beats the (fast, local) read still uploads with
 * `save=false` rather than guessing the user opted in. A set is applied to the
 * UI immediately and written through in the background; a failed write leaves
 * the on-screen state as the user set it for this session rather than silently
 * snapping the control back.
 *
 * There is deliberately no "hydrating" state for callers to branch on: the
 * default is the safe value, so the control can render its resting state
 * immediately and simply settle into a stored opt-in — no spinner, no
 * placeholder, nothing that moves under the user (*Calm by default*).
 */
export function useLabelSavePreference(
  store: LabelSavePreferenceStore = fileLabelSavePreferenceStore,
): LabelSavePreference {
  const [saveLabelPhotos, setState] = useState(DEFAULT_SAVE_LABEL_PHOTOS);
  // A user set during the in-flight hydrate must win: the hydrate only seeds.
  const userSet = useRef(false);

  useEffect(() => {
    let active = true;
    void store
      .get()
      .then((stored) => {
        if (!active || userSet.current) return;
        // Nothing to apply when the stored value is already the resting one —
        // the overwhelmingly common case, so the hydrate costs no re-render.
        if (stored === DEFAULT_SAVE_LABEL_PHOTOS) return;
        setState(stored);
      })
      .catch(() => {
        // Fail closed: keep the discard-by-default value.
      });
    return () => {
      active = false;
    };
  }, [store]);

  const setSaveLabelPhotos = useCallback(
    (next: boolean) => {
      userSet.current = true;
      setState(next);
      void store.set(next).catch(() => {
        // Best-effort persistence: the choice still holds for this session.
      });
    },
    [store],
  );

  return { saveLabelPhotos, setSaveLabelPhotos };
}
