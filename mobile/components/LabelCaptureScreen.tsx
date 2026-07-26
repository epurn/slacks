/**
 * Nutrition-label capture screen (FTY-064; two-tap flow in FTY-433).
 *
 * Reuses the FTY-063 camera scaffold (CameraCapture) for permission handling so
 * neither the expo-camera dependency nor the OS permission plumbing is re-added
 * here. The permission rationale is label-specific and displayed before the first
 * capture.
 *
 * Flow (FTY-433):
 *   camera → (shutter) → uploading → done (the host handles the capture)
 *                                  → (retake) → camera
 *
 * The shutter **is** the submit: capturing a frame starts the upload
 * immediately, so the steady-state label path is open → shutter → confirm, two
 * taps before the parse-confirm gate (the barcode flow is one). The old blocking
 * preview with its separate `Upload` button and its per-capture "Save this
 * photo?" question are gone; the captured frame is the uploading state's
 * backdrop, and `Retake` stays available as an *optional undo* for a blurry shot
 * rather than a required decision.
 *
 * The component is a reusable label-capture surface (FTY-311): it owns the
 * camera, the uploading/error phases, and the sticky save preference, but it
 * does not assume what happens on submit. The single `onSubmit` handler receives
 * the captured image URI, the save-photo flag, and an abort signal, and decides
 * the outcome:
 *   - the normal Today host uploads via `uploadLabelImage` and opens the
 *     confirm-parsed-values flow;
 *   - an exact-evidence host (FTY-312) receives the same capture to attach as
 *     evidence, without the capture component assuming a `LogEventDTO` comes
 *     back.
 * A rejected `onSubmit` surfaces the in-place error state; the mapping of known
 * label-upload errors to friendly copy stays here so the normal host keeps its
 * error UX for free.
 *
 * Retake during an upload **supersedes** it: the capture's `AbortSignal` is
 * aborted, this component ignores the outcome, and a host that honours the
 * signal (TodayScreen does) drops the result instead of yanking the user into a
 * confirm sheet for a shot they already discarded. The network request itself is
 * not cancellable through the native upload API, so an aborted capture may still
 * land server-side as an unconfirmed proposal — exactly the state an abandoned
 * confirm sheet already leaves behind, and never a counted entry. Its image is
 * retained only if the user had already turned saving on, which is the same
 * retention their choice buys for any other capture: nothing is persisted that
 * `save=false` would have discarded.
 *
 * Retention (FTY-077, unchanged): the raw image is persisted only when the
 * upload carries `save=true`. That flag now comes from the **sticky, default-off
 * save preference** (`state/labelSavePreference.ts`) read at shutter time and
 * surfaced as a quiet control in the camera chrome, instead of a question asked
 * on every capture. Discard-by-default is a hard invariant: the preference
 * defaults off and fails closed, so a steady-state capture uploads with
 * `save=false` and the backend discards the image after extraction.
 *
 * Photo-library fallback (FTY-381): the live camera is unavailable on the iOS
 * simulator (no hardware camera) and `takePictureAsync` yields a blank/failing
 * frame there, so the camera phase also offers a first-party "Choose from
 * Library" pick (`expo-image-picker`). This is a genuine user path — a label
 * photo already in the library — and the honest degrade when live capture can't
 * produce a frame; it starts the same auto-upload with the same `save`
 * semantics. The picked asset is ephemeral, treated identically to a capture:
 * its URI is handed only to `onSubmit` and never persisted or logged here.
 *
 * Security: the captured/picked image is not retained on-device beyond this flow
 * — the URI is handed only to the caller-provided `onSubmit`. Errors carry only
 * HTTP status — never image bytes, URIs, or extracted content. Camera permission
 * is handled by CameraCapture (FTY-063), reused without changes; the library
 * pick uses `launchImageLibraryAsync`, which needs no photo-library permission
 * (iOS presents the out-of-process picker), so no extra permission is requested.
 */

import { useCallback, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Animated,
  Image,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { CameraView } from "expo-camera";
import * as ImagePicker from "expo-image-picker";

import {
  LabelUploadApiError,
  LabelUploadInvalidTypeError,
  LabelUploadTooLargeError,
} from "@/api/labelCapture";
import {
  useLabelSavePreference,
  type LabelSavePreferenceStore,
} from "@/state/labelSavePreference";
import { useTheme } from "@/theme/ThemeContext";
import { useResolveFade } from "@/theme/motion";
import { typeScale } from "@/theme/typography";
import type { ColorPalette } from "@/theme/colors";
import { AppIcon } from "@/components/ui";
import {
  CameraCapture,
  type CameraCaptureProps,
} from "@/components/CameraCapture";

const RATIONALE =
  "Slacks uses the camera to photograph nutrition labels so you can log packaged foods accurately.";

const FRAMING_HINT = "Fit the nutrition label inside the frame";

/** The sticky save control's copy — the label is also its accessibility label. */
const SAVE_TOGGLE_LABEL = "Save label photos";
const SAVE_TOGGLE_ON_CAPTION = "Saving photos";
const SAVE_TOGGLE_HINT =
  "When on, every label photo you take is kept as an attachment. Off by default — the photo is discarded once the label is read. Your choice sticks until you change it.";

type Phase = "camera" | "uploading" | "error";

/** A captured photo ready to upload: URI from CameraView.takePictureAsync. */
interface CapturedPhoto {
  uri: string;
}

/** A captured label handed to the submit handler. */
export interface LabelCapture {
  /**
   * Local file URI of the captured label image. Ephemeral: it exists only long
   * enough for `onSubmit` to consume it and is never persisted by this
   * component.
   */
  imageUri: string;
  /**
   * Whether the user opted to keep the photo — the sticky save preference read
   * at shutter time. Defaults off (discard-by-default, FTY-077).
   */
  savePhoto: boolean;
  /**
   * Aborted when the user retakes while this capture is still uploading. A host
   * must check it before applying the result (opening a sheet, mutating a
   * timeline): the user has moved on to a new shot, and a superseded upload must
   * not surface.
   */
  signal: AbortSignal;
}

export interface LabelCaptureScreenProps {
  /**
   * Handles a captured label. Receives the image URI, the save-photo flag, and
   * the capture's abort signal. The normal Today host uploads via
   * `uploadLabelImage` and opens the confirm-parsed-values flow; an
   * exact-evidence host (FTY-312) receives the capture for its own use. Reject
   * to surface the in-place error state. Must not persist or log the URI beyond
   * its own handling, and must not apply its result once `signal` is aborted.
   */
  onSubmit: (capture: LabelCapture) => Promise<void>;
  onClose: () => void;
  /**
   * Injectable photo capture for tests. Defaults to calling
   * `cameraRef.current.takePictureAsync`. Receives no arguments and returns
   * the captured photo URI.
   */
  takePhoto?: () => Promise<CapturedPhoto>;
  /**
   * Injectable photo-library pick for tests. Defaults to
   * `expo-image-picker`'s `launchImageLibraryAsync`. Resolves to the picked
   * photo, or `null` when the user cancels the picker.
   */
  pickPhoto?: () => Promise<CapturedPhoto | null>;
  /** Injectable for tests; forwarded to CameraCapture. */
  permissionsHook?: CameraCaptureProps["permissionsHook"];
  /**
   * Injectable persistence for the sticky save preference (FTY-433). Defaults
   * to the on-device file store.
   */
  savePreferenceStore?: LabelSavePreferenceStore;
}

/** Map an upload failure to a plain, nonjudgmental message without image content. */
function messageFor(error: unknown): string {
  if (error instanceof LabelUploadTooLargeError) return error.message;
  if (error instanceof LabelUploadInvalidTypeError) return error.message;
  if (error instanceof LabelUploadApiError) return error.message;
  return "We couldn't upload that label. Please try again.";
}

/**
 * Full-screen label capture. Wraps the camera in the FTY-063 permission gate and
 * drives the shutter straight into the upload, with the captured frame and a
 * Retake as the uploading state. Use inside a Modal from TodayScreen.
 */
export function LabelCaptureScreen({
  onSubmit,
  onClose,
  takePhoto,
  pickPhoto,
  permissionsHook,
  savePreferenceStore,
}: LabelCaptureScreenProps) {
  const { colors } = useTheme();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const cameraRef = useRef<CameraView>(null);
  const [phase, setPhase] = useState<Phase>("camera");
  const [photo, setPhoto] = useState<CapturedPhoto | null>(null);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [torchOn, setTorchOn] = useState(false);
  // Monotonic per-capture id: remounts the uploading state so its entrance fade
  // replays for each new shot, and never reuses a superseded capture's frame.
  const [captureId, setCaptureId] = useState(0);
  // The in-flight capture's abort handle — aborted by Retake, so a superseded
  // upload neither errors here nor reaches the host's success path.
  const abortRef = useRef<AbortController | null>(null);
  const { saveLabelPhotos, setSaveLabelPhotos } =
    useLabelSavePreference(savePreferenceStore);

  const defaultTakePhoto = useCallback(async (): Promise<CapturedPhoto> => {
    const result = await cameraRef.current?.takePictureAsync({ quality: 0.8 });
    if (!result) {
      throw new Error("Camera is not ready. Please try again.");
    }
    return { uri: result.uri };
  }, []);

  const defaultPickPhoto = useCallback(async (): Promise<CapturedPhoto | null> => {
    // `launchImageLibraryAsync` uses the OS out-of-process picker on iOS, which
    // needs no photo-library permission and returns a single image asset.
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: "images",
      quality: 0.8,
      selectionLimit: 1,
    });
    if (result.canceled || result.assets.length === 0) return null;
    return { uri: result.assets[0].uri };
  }, []);

  const doTakePhoto = takePhoto ?? defaultTakePhoto;
  const doPickPhoto = pickPhoto ?? defaultPickPhoto;

  // The flash control only exists in the camera/error phases, so gate the torch
  // to those phases: once the user leaves (uploading), the torch turns off even
  // though `torchOn` is retained for when they return to framing.
  const torchActive = torchOn && (phase === "camera" || phase === "error");

  /**
   * Start the upload for a freshly captured/picked frame. Called straight from
   * the shutter (and the library pick) — there is no intermediate confirm step.
   * The sticky save preference is read here, at shutter time, and travels with
   * the capture as the `?save=` retention flag.
   */
  const startUpload = useCallback(
    async (captured: CapturedPhoto) => {
      const controller = new AbortController();
      abortRef.current = controller;
      setPhoto(captured);
      setUploadError(null);
      setCaptureId((prev) => prev + 1);
      setPhase("uploading");
      try {
        // The host decides the outcome (upload + confirm-parsed, or attach as
        // exact evidence). On success it advances/closes; this component adds no
        // further state so there is no update after a possible unmount.
        await onSubmit({
          imageUri: captured.uri,
          savePhoto: saveLabelPhotos,
          signal: controller.signal,
        });
      } catch (error) {
        // A superseded capture's failure is not the user's problem: they are
        // already back at the viewfinder framing the next shot.
        if (controller.signal.aborted) return;
        // Error message must not contain image bytes, URIs, or extracted content.
        setUploadError(messageFor(error));
        setPhoto(null);
        setPhase("error");
      }
    },
    [onSubmit, saveLabelPhotos],
  );

  const handleShutter = useCallback(async () => {
    let captured: CapturedPhoto;
    try {
      captured = await doTakePhoto();
    } catch {
      // Camera not ready — stay on the camera surface; no sensitive content to log.
      setUploadError("Couldn't capture the photo. Please try again.");
      setPhase("error");
      return;
    }
    await startUpload(captured);
  }, [doTakePhoto, startUpload]);

  const handlePickFromLibrary = useCallback(async () => {
    let picked: CapturedPhoto | null;
    try {
      picked = await doPickPhoto();
    } catch {
      // Picker failed to open/read — surface an actionable, content-free error.
      setUploadError("Couldn't open your photo library. Please try again.");
      setPhase("error");
      return;
    }
    if (!picked) return; // user canceled the picker — stay in the camera phase
    await startUpload(picked);
  }, [doPickPhoto, startUpload]);

  const handleRetake = useCallback(() => {
    // Supersede the in-flight upload before returning to framing.
    abortRef.current?.abort();
    abortRef.current = null;
    setPhoto(null);
    setUploadError(null);
    setPhase("camera");
  }, []);

  const framing = phase === "camera" || phase === "error";

  return (
    <CameraCapture
      onClose={onClose}
      rationale={RATIONALE}
      permissionsHook={permissionsHook}
    >
      {() => (
        <View style={StyleSheet.absoluteFill}>
          <CameraView
            ref={cameraRef}
            style={StyleSheet.absoluteFill}
            facing="back"
            enableTorch={torchActive}
            accessibilityLabel="Camera viewfinder"
          />

          {framing && <FramingGuide colors={colors} />}

          {framing && (
            <FlashToggle
              torchOn={torchOn}
              onToggle={() => setTorchOn((prev) => !prev)}
              colors={colors}
            />
          )}

          {framing && (
            <SavePhotosToggle
              saveLabelPhotos={saveLabelPhotos}
              onToggle={() => setSaveLabelPhotos(!saveLabelPhotos)}
              colors={colors}
            />
          )}

          {/* Overlay controls rendered on top of the viewfinder */}
          <View style={styles.overlay}>
            {framing && (
              <ShutterControls
                onShutter={() => void handleShutter()}
                onPickFromLibrary={() => void handlePickFromLibrary()}
                error={phase === "error" ? uploadError : null}
                colors={colors}
              />
            )}

            {phase === "uploading" && photo && (
              <UploadingState
                key={captureId}
                photoUri={photo.uri}
                onRetake={handleRetake}
                colors={colors}
              />
            )}
          </View>
        </View>
      )}
    </CameraCapture>
  );
}

function FramingGuide({ colors }: { colors: ColorPalette }) {
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return (
    <View style={styles.framingGuideContainer} pointerEvents="none">
      <View style={styles.framingGuideFrame} />
      <Text
        style={styles.framingHintText}
        accessibilityRole="text"
        accessibilityLabel={FRAMING_HINT}
      >
        {FRAMING_HINT}
      </Text>
    </View>
  );
}

function FlashToggle({
  torchOn,
  onToggle,
  colors,
}: {
  torchOn: boolean;
  onToggle: () => void;
  colors: ColorPalette;
}) {
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Flash"
      accessibilityHint="Toggles the camera flash for the label photo"
      accessibilityState={{ selected: torchOn }}
      onPress={onToggle}
      style={styles.flashButton}
    >
      <AppIcon
        name={torchOn ? "bolt.fill" : "bolt.slash.fill"}
        size={20}
        color="#FFFFFF"
      />
    </Pressable>
  );
}

/**
 * The sticky save-photo preference (FTY-433), sitting quietly in the camera
 * chrome opposite the flash toggle — not a step on the capture path.
 *
 * Off is the discard-by-default resting state and stays icon-only. Turning it on
 * is a deliberate act, so the on state is unmistakable and *persistent*: the
 * glyph fills, takes the accent, and gains a "Saving photos" caption that is
 * still there next time the user opens capture.
 */
function SavePhotosToggle({
  saveLabelPhotos,
  onToggle,
  colors,
}: {
  saveLabelPhotos: boolean;
  onToggle: () => void;
  colors: ColorPalette;
}) {
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return (
    <View style={styles.saveToggleContainer}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={SAVE_TOGGLE_LABEL}
        accessibilityHint={SAVE_TOGGLE_HINT}
        accessibilityState={{ selected: saveLabelPhotos }}
        onPress={onToggle}
        style={[styles.saveToggle, saveLabelPhotos && styles.saveToggleOn]}
      >
        <AppIcon
          name={
            saveLabelPhotos
              ? "square.and.arrow.down.fill"
              : "square.and.arrow.down"
          }
          size={20}
          color={saveLabelPhotos ? colors.accent : "#FFFFFF"}
        />
      </Pressable>
      {/* The sticky state as a status line, not part of the button's label: a
          child Text inside a labelled Pressable is folded away on iOS, so this
          sits outside it — readable by VoiceOver and visible at a glance. */}
      {saveLabelPhotos ? (
        <Text
          style={styles.saveToggleCaption}
          accessibilityRole="text"
          accessibilityLabel={SAVE_TOGGLE_ON_CAPTION}
        >
          {SAVE_TOGGLE_ON_CAPTION}
        </Text>
      ) : null}
    </View>
  );
}

function ShutterControls({
  onShutter,
  onPickFromLibrary,
  error,
  colors,
}: {
  onShutter: () => void;
  onPickFromLibrary: () => void;
  error: string | null;
  colors: ColorPalette;
}) {
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return (
    <View style={styles.shutterControls}>
      {error ? (
        <Text
          style={styles.errorText}
          accessibilityRole="alert"
          accessibilityLabel={error}
        >
          {error}
        </Text>
      ) : null}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Take photo"
        accessibilityHint="Captures the nutrition label and uploads it right away"
        onPress={onShutter}
        style={styles.shutterButton}
      >
        <View style={styles.shutterInner} />
      </Pressable>
      {/* Photo-library fallback (FTY-381): the honest degrade when the live
          camera can't produce a frame (e.g. the camera-less iOS simulator) and a
          genuine path for a label photo already in the library. */}
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="Choose from Library"
        accessibilityHint="Pick a nutrition-label photo from your library instead of the camera"
        onPress={onPickFromLibrary}
        style={styles.libraryButton}
      >
        <AppIcon name="photo.on.rectangle" size={18} color="#FFFFFF" />
        <Text style={styles.libraryButtonLabel}>Choose from Library</Text>
      </Pressable>
    </View>
  );
}

/**
 * The uploading state (FTY-433): the frame the user just shot, held still while
 * the upload runs, with a Retake escape hatch. It replaces the old blocking
 * preview — nothing here is a required decision.
 *
 * The frame settles in with the shared resolve fade (`theme/motion`) rather than
 * snapping over the live viewfinder, and degrades to a quick fade under Reduce
 * Motion. Mounted per capture (keyed on the capture id), so each new shot plays
 * its own entrance.
 */
function UploadingState({
  photoUri,
  onRetake,
  colors,
}: {
  photoUri: string;
  onRetake: () => void;
  colors: ColorPalette;
}) {
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const opacity = useResolveFade(true, /* startsHidden */ true);
  return (
    <>
      <Animated.View
        style={[StyleSheet.absoluteFill, { opacity }]}
        pointerEvents="none"
      >
        <Image
          source={{ uri: photoUri }}
          style={StyleSheet.absoluteFill}
          accessibilityLabel="Captured nutrition label photo"
          resizeMode="cover"
        />
        <View style={styles.uploadingScrim} />
      </Animated.View>

      <View style={styles.uploadingContainer}>
        <ActivityIndicator
          color="#FFFFFF"
          size="large"
          accessibilityLabel="Uploading label"
        />
        <Text style={styles.uploadingText}>Uploading…</Text>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Retake photo"
          accessibilityHint="Discards this shot and returns to the camera"
          onPress={onRetake}
          style={styles.retakeButton}
        >
          <Text style={styles.retakeButtonLabel}>Retake</Text>
        </Pressable>
      </View>
    </>
  );
}

function makeStyles(colors: ColorPalette) {
  return StyleSheet.create({
    overlay: {
      position: "absolute",
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      justifyContent: "flex-end",
      alignItems: "center",
      paddingBottom: 48,
    },
    shutterControls: {
      alignItems: "center",
      gap: 16,
    },
    framingGuideContainer: {
      position: "absolute",
      top: "16%",
      left: 0,
      right: 0,
      alignItems: "center",
      gap: 12,
    },
    framingGuideFrame: {
      // Overlay guide on the live camera feed, not a themed surface — fixed
      // translucent white to stay legible over any label/background.
      width: "76%",
      aspectRatio: 0.72,
      borderWidth: 3,
      borderColor: "rgba(255,255,255,0.85)",
      borderRadius: 16,
    },
    framingHintText: {
      // Sits over the live camera feed — fixed white for contrast, matching
      // the other camera-overlay text in this file.
      color: "#FFFFFF",
      fontSize: typeScale.subhead,
      fontWeight: "500",
      textAlign: "center",
      paddingHorizontal: 24,
      backgroundColor: "rgba(0,0,0,0.5)",
      borderRadius: 8,
      paddingVertical: 6,
    },
    flashButton: {
      position: "absolute",
      top: 60,
      left: 20,
      width: 44,
      height: 44,
      borderRadius: 22,
      backgroundColor: "rgba(0,0,0,0.6)",
      alignItems: "center",
      justifyContent: "center",
    },
    saveToggleContainer: {
      // Sits beside the flash control in the camera chrome's top row.
      // Deliberately NOT top-right: CameraCapture owns that corner for its close
      // button (`closeButton`, top: 60 / right: 20), and a control stacked under
      // the dismiss affordance is untappable. `left` clears the flash button's
      // 44pt footprint plus a gap; the status caption hangs below the button, so
      // the button itself never moves as the state changes.
      position: "absolute",
      top: 60,
      left: 76,
      alignItems: "center",
      gap: 6,
    },
    saveToggle: {
      // Matches the flash control's shape exactly — fixed translucent-black over
      // the live feed (not a themed surface).
      width: 44,
      height: 44,
      borderRadius: 22,
      backgroundColor: "rgba(0,0,0,0.6)",
      alignItems: "center",
      justifyContent: "center",
    },
    saveToggleOn: {
      // The deliberate, sticky opt-in reads as active chrome, not a stray tap.
      borderWidth: 1,
      borderColor: colors.accent,
    },
    saveToggleCaption: {
      // On a translucent-black chip over the camera feed, not a themed surface —
      // fixed white (the amber accent carries the on state through the glyph and
      // the button's hairline, where it is a fill/border, never text).
      color: "#FFFFFF",
      fontSize: typeScale.footnote,
      fontWeight: "600",
      backgroundColor: "rgba(0,0,0,0.6)",
      borderRadius: 8,
      paddingHorizontal: 8,
      paddingVertical: 3,
    },
    errorText: {
      color: colors.coral,
      fontSize: typeScale.subhead,
      textAlign: "center",
      paddingHorizontal: 24,
      backgroundColor: "rgba(0,0,0,0.7)",
      borderRadius: 8,
      paddingVertical: 8,
      maxWidth: 320,
    },
    shutterButton: {
      width: 72,
      height: 72,
      borderRadius: 36,
      backgroundColor: "rgba(255,255,255,0.9)",
      alignItems: "center",
      justifyContent: "center",
    },
    shutterInner: {
      // Inner disc of the shutter button over the live camera feed — fixed
      // white to match the translucent-white ring (`shutterButton`), not a
      // themed token (the camera feed is not a themed surface).
      width: 60,
      height: 60,
      borderRadius: 30,
      backgroundColor: "#FFFFFF",
      borderWidth: 2,
      borderColor: "rgba(255,255,255,0.6)",
    },
    libraryButton: {
      // Secondary "Choose from Library" control sitting under the shutter over
      // the live camera feed — fixed translucent-white chrome (the camera feed
      // is not a themed surface), matching the other camera-overlay controls.
      flexDirection: "row",
      alignItems: "center",
      gap: 8,
      paddingHorizontal: 18,
      paddingVertical: 10,
      borderRadius: 20,
      backgroundColor: "rgba(0,0,0,0.55)",
      minHeight: 44,
    },
    libraryButtonLabel: {
      color: "#FFFFFF",
      fontSize: typeScale.callout,
      fontWeight: "600",
    },
    uploadingScrim: {
      // Dims the held frame so the spinner, copy, and Retake stay legible over
      // any label. Fixed black over a photo, not a themed surface.
      position: "absolute",
      top: 0,
      left: 0,
      right: 0,
      bottom: 0,
      backgroundColor: "rgba(0,0,0,0.45)",
    },
    uploadingContainer: {
      alignItems: "center",
      gap: 12,
    },
    uploadingText: {
      // Rendered over the held capture — fixed white for contrast.
      color: "#FFFFFF",
      fontSize: typeScale.callout,
      fontWeight: "500",
    },
    retakeButton: {
      // The optional undo: present and reachable, but visibly secondary to the
      // upload that is already under way.
      marginTop: 4,
      paddingHorizontal: 24,
      paddingVertical: 12,
      borderRadius: 10,
      backgroundColor: "rgba(255,255,255,0.2)",
      alignItems: "center",
      justifyContent: "center",
      minHeight: 44,
    },
    retakeButtonLabel: {
      // Translucent-white button over the held capture — fixed white, not a
      // themed token.
      color: "#FFFFFF",
      fontSize: typeScale.callout,
      fontWeight: "600",
    },
  });
}
