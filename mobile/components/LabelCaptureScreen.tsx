/**
 * Nutrition-label capture screen (FTY-064).
 *
 * Reuses the FTY-063 camera scaffold (CameraCapture) for permission handling so
 * neither the expo-camera dependency nor the OS permission plumbing is re-added
 * here. The permission rationale is label-specific and displayed before the first
 * capture.
 *
 * Flow:
 *   camera → (shutter) → preview → (submit) → done (host handles the capture)
 *                               → (retake)  → camera
 *
 * The component is a reusable label-capture surface (FTY-311): it owns the
 * camera, preview, save-photo toggle, and the loading/error phases, but it does
 * not assume what happens on submit. The single `onSubmit` handler receives the
 * captured image URI and the save-photo flag and decides the outcome:
 *   - the normal Today host uploads via `uploadLabelImage` and opens the
 *     confirm-parsed-values flow;
 *   - an exact-evidence host (FTY-312) receives the same capture to attach as
 *     evidence, without the capture component assuming a `LogEventDTO` comes
 *     back.
 * A rejected `onSubmit` surfaces the in-place error state; the mapping of known
 * label-upload errors to friendly copy stays here so the normal host keeps its
 * error UX for free.
 *
 * The "save this photo" toggle defaults to off (discard-by-default per FTY-077).
 * When on, the `savePhoto` flag is forwarded to the submit handler; the normal
 * host passes it to the label-upload endpoint, which persists the raw image as a
 * `log_attachment`; when off, the backend discards it after extraction.
 *
 * Photo-library fallback (FTY-381): the live camera is unavailable on the iOS
 * simulator (no hardware camera) and `takePictureAsync` yields a blank/failing
 * frame there, so the camera phase also offers a first-party "Choose from
 * Library" pick (`expo-image-picker`). This is a genuine user path — a label
 * photo already in the library — and the honest degrade when live capture can't
 * produce a frame; it feeds the exact same `onSubmit` handler and `save`
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
  Image,
  Pressable,
  StyleSheet,
  Switch,
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
import { useTheme } from "@/theme/ThemeContext";
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

type Phase = "camera" | "preview" | "uploading" | "error";

/** A captured photo ready for review: URI from CameraView.takePictureAsync. */
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
  /** Whether the user opted to keep the photo. Defaults off (discard-by-default). */
  savePhoto: boolean;
}

export interface LabelCaptureScreenProps {
  /**
   * Handles a captured label. Receives the image URI and the save-photo flag.
   * The normal Today host uploads via `uploadLabelImage` and opens the
   * confirm-parsed-values flow; an exact-evidence host (FTY-312) receives the
   * capture for its own use. Reject to surface the in-place error state. Must
   * not persist or log the URI beyond its own handling.
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
}

/** Map an upload failure to a plain, nonjudgmental message without image content. */
function messageFor(error: unknown): string {
  if (error instanceof LabelUploadTooLargeError) return error.message;
  if (error instanceof LabelUploadInvalidTypeError) return error.message;
  if (error instanceof LabelUploadApiError) return error.message;
  return "We couldn't upload that label. Please try again.";
}

/**
 * Full-screen label capture. Wraps the camera in the FTY-063 permission gate,
 * handles the photo review and save-photo opt-in, and drives the upload to the
 * label-upload endpoint. Use inside a Modal from TodayScreen.
 */
export function LabelCaptureScreen({
  onSubmit,
  onClose,
  takePhoto,
  pickPhoto,
  permissionsHook,
}: LabelCaptureScreenProps) {
  const { colors } = useTheme();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const cameraRef = useRef<CameraView>(null);
  const [phase, setPhase] = useState<Phase>("camera");
  const [photo, setPhoto] = useState<CapturedPhoto | null>(null);
  const [savePhoto, setSavePhoto] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [torchOn, setTorchOn] = useState(false);

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
  // to those phases: once the user leaves (preview/uploading), the torch turns
  // off even though `torchOn` is retained for when they return to framing.
  const torchActive = torchOn && (phase === "camera" || phase === "error");

  const handleShutter = useCallback(async () => {
    try {
      const captured = await doTakePhoto();
      setPhoto(captured);
      setPhase("preview");
    } catch {
      // Camera not ready — stay in camera phase; no sensitive content to log.
      setUploadError("Couldn't capture the photo. Please try again.");
      setPhase("error");
    }
  }, [doTakePhoto]);

  const handlePickFromLibrary = useCallback(async () => {
    try {
      const picked = await doPickPhoto();
      if (!picked) return; // user canceled the picker — stay in the camera phase
      setUploadError(null);
      setPhoto(picked);
      setPhase("preview");
    } catch {
      // Picker failed to open/read — surface an actionable, content-free error.
      setUploadError("Couldn't open your photo library. Please try again.");
      setPhase("error");
    }
  }, [doPickPhoto]);

  const handleRetake = useCallback(() => {
    setPhoto(null);
    setSavePhoto(false);
    setUploadError(null);
    setPhase("camera");
  }, []);

  const handleUpload = useCallback(async () => {
    if (!photo) return;
    setPhase("uploading");
    setUploadError(null);
    try {
      // The host decides the outcome (upload + confirm-parsed, or attach as
      // exact evidence). On success it advances/closes; this component adds no
      // further state so there is no update after a possible unmount.
      await onSubmit({ imageUri: photo.uri, savePhoto });
    } catch (error) {
      // Error message must not contain image bytes, URIs, or extracted content.
      setUploadError(messageFor(error));
      setPhase("error");
    }
  }, [photo, savePhoto, onSubmit]);

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

          {(phase === "camera" || phase === "error") && (
            <FramingGuide colors={colors} />
          )}

          {(phase === "camera" || phase === "error") && (
            <FlashToggle
              torchOn={torchOn}
              onToggle={() => setTorchOn((prev) => !prev)}
              colors={colors}
            />
          )}

          {/* Overlay controls rendered on top of the viewfinder */}
          <View style={styles.overlay}>
            {(phase === "camera" || phase === "error") && (
              <ShutterControls
                onShutter={() => void handleShutter()}
                onPickFromLibrary={() => void handlePickFromLibrary()}
                error={phase === "error" ? uploadError : null}
                colors={colors}
              />
            )}

            {phase === "preview" && photo && (
              <PreviewControls
                photoUri={photo.uri}
                savePhoto={savePhoto}
                onToggleSave={setSavePhoto}
                onRetake={handleRetake}
                onUpload={() => void handleUpload()}
                colors={colors}
              />
            )}

            {phase === "uploading" && (
              <View style={styles.uploadingContainer}>
                <ActivityIndicator
                  color="#FFFFFF"
                  size="large"
                  accessibilityLabel="Uploading label"
                />
                <Text style={styles.uploadingText}>Uploading…</Text>
              </View>
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
        accessibilityHint="Captures a photo of the nutrition label"
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

function PreviewControls({
  photoUri,
  savePhoto,
  onToggleSave,
  onRetake,
  onUpload,
  colors,
}: {
  photoUri: string;
  savePhoto: boolean;
  onToggleSave: (value: boolean) => void;
  onRetake: () => void;
  onUpload: () => void;
  colors: ColorPalette;
}) {
  const styles = useMemo(() => makeStyles(colors), [colors]);
  return (
    <View style={styles.previewControls}>
      <Image
        source={{ uri: photoUri }}
        style={styles.previewImage}
        accessibilityLabel="Captured nutrition label photo"
        resizeMode="contain"
      />
      <View style={styles.saveRow}>
        <Text style={styles.saveLabel}>Save this photo</Text>
        <Switch
          accessibilityLabel="Save this photo"
          accessibilityHint="When on, the photo is saved as an attachment. Default is off — the photo is discarded after the label is read."
          value={savePhoto}
          onValueChange={onToggleSave}
          trackColor={{ false: colors.textSecondary, true: colors.accent }}
          thumbColor="#FFFFFF"
        />
      </View>
      <View style={styles.previewActions}>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Retake photo"
          onPress={onRetake}
          style={styles.secondaryButton}
        >
          <Text style={styles.secondaryButtonLabel}>Retake</Text>
        </Pressable>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="Upload label"
          accessibilityHint="Uploads the photo to extract nutrition information"
          onPress={onUpload}
          style={styles.primaryButton}
        >
          <Text style={styles.primaryButtonLabel}>Upload</Text>
        </Pressable>
      </View>
    </View>
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
    previewControls: {
      width: "100%",
      paddingHorizontal: 24,
      gap: 16,
      alignItems: "center",
    },
    previewImage: {
      // Placeholder behind the captured label image in the camera UI — fixed
      // dark so the container stays a dark placeholder in both light and dark
      // (a themed token like `colors.text`/`colors.surface` would flip to
      // near-white in dark mode).
      width: "100%",
      height: 240,
      borderRadius: 12,
      backgroundColor: "#1C1C1E",
    },
    saveRow: {
      flexDirection: "row",
      alignItems: "center",
      justifyContent: "space-between",
      width: "100%",
      backgroundColor: "rgba(0,0,0,0.6)",
      borderRadius: 10,
      paddingHorizontal: 16,
      paddingVertical: 12,
      minHeight: 44,
    },
    saveLabel: {
      // Sits in a dark scrim over the live camera feed, not on a themed
      // surface — fixed white for contrast in both light and dark (matches
      // CameraCapture's overlay text).
      color: "#FFFFFF",
      fontSize: typeScale.callout,
      fontWeight: "500",
    },
    previewActions: {
      flexDirection: "row",
      gap: 12,
      width: "100%",
    },
    secondaryButton: {
      flex: 1,
      backgroundColor: "rgba(255,255,255,0.2)",
      borderRadius: 10,
      paddingVertical: 14,
      alignItems: "center",
      minHeight: 44,
    },
    secondaryButtonLabel: {
      // Translucent-white button over the camera feed — fixed white, not a
      // themed token (the camera feed is not a themed surface).
      color: "#FFFFFF",
      fontSize: typeScale.callout,
      fontWeight: "600",
    },
    primaryButton: {
      flex: 2,
      backgroundColor: colors.accent,
      borderRadius: 10,
      paddingVertical: 14,
      alignItems: "center",
      minHeight: 44,
    },
    primaryButtonLabel: {
      // The only overlay label on the amber accent fill (`primaryButton`), so
      // accentForeground is the correct on-accent token here.
      color: colors.accentForeground,
      fontSize: typeScale.callout,
      fontWeight: "600",
    },
    uploadingContainer: {
      alignItems: "center",
      gap: 12,
    },
    uploadingText: {
      // Rendered directly on the live camera feed — fixed white for contrast.
      color: "#FFFFFF",
      fontSize: typeScale.callout,
      fontWeight: "500",
    },
  });
}
