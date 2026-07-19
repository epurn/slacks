/**
 * Today composer image attachments (FTY-383).
 *
 * Owns the attach affordance's state for the unified text+image submission
 * (`docs/contracts/log-event-images.md`): the picked images, the
 * source chooser (photo library / camera) via `expo-image-picker`, the
 * first-line client-side guard (count / size / content type, mirroring
 * `labelCapture.ts`), and the calm, content-free attach error. The submit
 * itself lives in the submit machine (`useTodaySubmit`); this hook only
 * curates what will be sent.
 *
 * Design philosophy: the chooser is a native iOS action sheet (never a bespoke
 * control); a denied camera permission or a picker failure surfaces a calm,
 * non-blocking message and never stops text logging. Picked URIs are ephemeral
 * — held only for the compose/submit lifecycle, handed to the submit client,
 * and never persisted or logged here.
 *
 * The three picker seams are injectable so the Today screen can be driven in
 * tests and, in E2E mode, so a hermetic fixture image stands in for the OS
 * picker (Maestro cannot drive the out-of-process photo picker) — the same
 * seam pattern as the camera-permission hook.
 */

import { useCallback, useMemo, useState } from "react";
import { ActionSheetIOS, Platform } from "react-native";
import * as ImagePicker from "expo-image-picker";

import type { SubmissionImage } from "@/api/logEvents";
import {
  MAX_UPLOAD_BYTES,
  validateImageGuard,
  LabelUploadTooLargeError,
  LabelUploadInvalidTypeError,
} from "@/api/labelCapture";
import { isE2EMode } from "@/e2e/launchMode";

/**
 * Maximum images per submission — the FTY-374 `MAX_SUBMISSION_IMAGES`, mirrored
 * client-side as the first-line guard. The backend is authoritative.
 */
export const MAX_SUBMISSION_IMAGES = 4;

/** A picked image staged in the composer: a submission part plus its size. */
export interface ComposerImage extends SubmissionImage {
  /** Byte size (0 when the picker doesn't report one; guarded backend-side). */
  readonly size: number;
}

/** Which source the chooser resolved to, or null when the user cancelled. */
type ImageSource = "library" | "camera";

/** Injectable picker seams (defaults use `expo-image-picker`; E2E returns a fixture). */
export interface ComposerImagePickers {
  /** Present the native source chooser; resolves the picked source or null. */
  presentSourceChooser: () => Promise<ImageSource | null>;
  /** Pick up to `remaining` images from the photo library (null = cancelled). */
  pickFromLibrary: (remaining: number) => Promise<ComposerImage[] | null>;
  /** Capture one image from the camera (null = cancelled). */
  captureFromCamera: () => Promise<ComposerImage | null>;
  /** Request camera permission; resolves whether it is granted. */
  requestCameraPermission: () => Promise<boolean>;
}

// A small label-like PNG data URI: the hermetic stand-in the E2E picker returns
// so a Maestro flow can attach a photo without the OS picker (the mocked fetch
// never reads the bytes; the thumbnail just needs a displayable image).
const E2E_FIXTURE_IMAGE: ComposerImage = {
  uri:
    "data:image/png;base64," +
    "iVBORw0KGgoAAAANSUhEUgAAABgAAAAYCAIAAABvFaqvAAAAJ0lEQVR42mN4MY2HKohh1KBRg6DIRkOEJDQSDRpNR6PpaDQd0cwgAArT7Z8dL53NAAAAAElFTkSuQmCC",
  name: "photo.png",
  type: "image/png",
  size: 189,
};

/** Map a picker asset to a composer image, normalizing type + name. */
function assetToImage(asset: ImagePicker.ImagePickerAsset): ComposerImage {
  const declared = (asset.mimeType ?? "").split(";")[0].trim().toLowerCase();
  const type = declared || "image/jpeg";
  const ext = type.split("/")[1] ?? "jpg";
  return {
    uri: asset.uri,
    name: asset.fileName ?? `photo.${ext === "jpeg" ? "jpg" : ext}`,
    type,
    size: asset.fileSize ?? 0,
  };
}

const defaultPickers: ComposerImagePickers = {
  async presentSourceChooser() {
    // In E2E mode there is no OS chooser to drive — go straight to the library
    // fixture so the hermetic Maestro flow can attach a photo deterministically.
    if (isE2EMode()) return "library";
    if (Platform.OS !== "ios") return "library";
    return new Promise<ImageSource | null>((resolve) => {
      ActionSheetIOS.showActionSheetWithOptions(
        {
          options: ["Cancel", "Photo Library", "Camera"],
          cancelButtonIndex: 0,
          title: "Attach a photo",
        },
        (index) => {
          if (index === 1) resolve("library");
          else if (index === 2) resolve("camera");
          else resolve(null);
        },
      );
    });
  },
  async pickFromLibrary(remaining) {
    if (isE2EMode()) return [E2E_FIXTURE_IMAGE];
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: "images",
      allowsMultipleSelection: true,
      selectionLimit: remaining,
      quality: 0.8,
    });
    if (result.canceled || result.assets.length === 0) return null;
    return result.assets.map(assetToImage);
  },
  async captureFromCamera() {
    if (isE2EMode()) return E2E_FIXTURE_IMAGE;
    const result = await ImagePicker.launchCameraAsync({
      mediaTypes: "images",
      quality: 0.8,
    });
    if (result.canceled || result.assets.length === 0) return null;
    return assetToImage(result.assets[0]);
  },
  async requestCameraPermission() {
    if (isE2EMode()) return true;
    const { granted } = await ImagePicker.requestCameraPermissionsAsync();
    return granted;
  },
};

/** Turn a guard rejection into its calm, content-free message. */
function guardMessage(error: unknown): string {
  if (
    error instanceof LabelUploadTooLargeError ||
    error instanceof LabelUploadInvalidTypeError
  ) {
    return error.message;
  }
  return "We couldn't add that photo. Please try a different one.";
}

/** What the Today composer needs to render and drive the attach affordance. */
export interface UseComposerImages {
  readonly images: readonly ComposerImage[];
  /** Present the chooser, pick, guard, and append — one attach interaction. */
  attach: () => Promise<void>;
  /** Remove the attachment at `index`. */
  removeImage: (index: number) => void;
  /** Drop every attachment (post-submit clear). */
  clearImages: () => void;
  /** Replace the whole set (restore on a failed submit). */
  setImages: (images: readonly ComposerImage[]) => void;
  /** Calm, content-free attach error (null when none). */
  readonly attachError: string | null;
}

/**
 * Manage the composer's attached images. `pickers` is injectable so the Today
 * screen can drive attach deterministically in tests; the default uses
 * `expo-image-picker` (and the hermetic fixture in E2E mode).
 */
export function useComposerImages(
  pickers: Partial<ComposerImagePickers> = {},
): UseComposerImages {
  const seams = useMemo(() => ({ ...defaultPickers, ...pickers }), [pickers]);
  const [images, setImagesState] = useState<readonly ComposerImage[]>([]);
  const [attachError, setAttachError] = useState<string | null>(null);

  const attach = useCallback(async () => {
    setAttachError(null);
    const remaining = MAX_SUBMISSION_IMAGES - images.length;
    if (remaining <= 0) {
      setAttachError(`You can attach up to ${MAX_SUBMISSION_IMAGES} photos.`);
      return;
    }

    const source = await seams.presentSourceChooser();
    if (!source) return;

    let picked: ComposerImage[] | null;
    try {
      if (source === "camera") {
        const granted = await seams.requestCameraPermission();
        if (!granted) {
          setAttachError(
            "Camera access is off. You can still type your log or choose from your library.",
          );
          return;
        }
        const shot = await seams.captureFromCamera();
        picked = shot ? [shot] : null;
      } else {
        picked = await seams.pickFromLibrary(remaining);
      }
    } catch {
      // Picker failed to open/read — calm, content-free, never blocks text.
      setAttachError("We couldn't open your photos. Please try again.");
      return;
    }

    if (!picked || picked.length === 0) return; // cancelled

    const accepted: ComposerImage[] = [];
    let countLimited = false;
    let guardRejected = false;
    for (const image of picked) {
      if (images.length + accepted.length >= MAX_SUBMISSION_IMAGES) {
        countLimited = true;
        break;
      }
      try {
        validateImageGuard(image.size, image.type);
        accepted.push(image);
      } catch (error) {
        guardRejected = true;
        setAttachError(guardMessage(error));
      }
    }
    // A size/type rejection carries the specific, more useful reason (set
    // above), so it wins over the generic count-limit message when a
    // multi-select batch trips both (an oversize/wrong-type image AND the
    // 4-photo ceiling). Only surface the count message when the count limit was
    // the sole reason anything was dropped.
    if (countLimited && !guardRejected) {
      setAttachError(`You can attach up to ${MAX_SUBMISSION_IMAGES} photos.`);
    }
    if (accepted.length > 0) {
      setImagesState((prev) => [...prev, ...accepted]);
    }
  }, [images, seams]);

  const removeImage = useCallback((index: number) => {
    setAttachError(null);
    setImagesState((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const clearImages = useCallback(() => {
    setAttachError(null);
    setImagesState([]);
  }, []);

  const setImages = useCallback((next: readonly ComposerImage[]) => {
    setImagesState(next);
  }, []);

  return { images, attach, removeImage, clearImages, setImages, attachError };
}

/** Re-exported for the guard-size reference in tests/consumers. */
export { MAX_UPLOAD_BYTES };
