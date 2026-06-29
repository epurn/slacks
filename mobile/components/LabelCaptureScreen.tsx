/**
 * Nutrition-label capture screen (FTY-064).
 *
 * Reuses the FTY-063 camera scaffold (CameraCapture) for permission handling so
 * neither the expo-camera dependency nor the OS permission plumbing is re-added
 * here. The permission rationale is label-specific and displayed before the first
 * capture.
 *
 * Flow:
 *   camera → (shutter) → preview → (upload) → done (calls onUploaded)
 *                               → (retake)  → camera
 *
 * The "save this photo" toggle defaults to off (discard-by-default per FTY-077).
 * When on, the `save` flag is forwarded to the label-upload endpoint, which
 * persists the raw image as a `log_attachment`; when off, the backend discards it
 * after extraction.
 *
 * Security: the captured image is not retained on-device beyond this flow.
 * Errors carry only HTTP status — never image bytes, URIs, or extracted content.
 * Camera permission is handled by CameraCapture (FTY-063), reused without changes.
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

import {
  LabelUploadApiError,
  LabelUploadInvalidTypeError,
  LabelUploadTooLargeError,
  uploadLabelImage as uploadLabelImageApi,
} from "@/api/labelCapture";
import { useTheme } from "@/theme/ThemeContext";
import type { ColorPalette } from "@/theme/colors";
import {
  CameraCapture,
  type CameraCaptureProps,
} from "@/components/CameraCapture";
import type { ApiSession } from "@/state/session";
import type { LogEventDTO } from "@/api/logEvents";

const RATIONALE =
  "Fatty uses the camera to photograph nutrition labels so you can log packaged foods accurately.";

type Phase = "camera" | "preview" | "uploading" | "error";

/** A captured photo ready for review: URI from CameraView.takePictureAsync. */
interface CapturedPhoto {
  uri: string;
}

export interface LabelCaptureScreenProps {
  /** Called after a successful upload with the resulting log event. */
  onUploaded: (event: LogEventDTO) => void;
  onClose: () => void;
  session: ApiSession;
  /**
   * Injectable upload function for tests. Defaults to `uploadLabelImage`.
   * Receives the image URI, the save flag, and returns the resulting event.
   */
  upload?: (imageUri: string, savePhoto: boolean) => Promise<LogEventDTO>;
  /**
   * Injectable photo capture for tests. Defaults to calling
   * `cameraRef.current.takePictureAsync`. Receives no arguments and returns
   * the captured photo URI.
   */
  takePhoto?: () => Promise<CapturedPhoto>;
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
  onUploaded,
  onClose,
  session,
  upload,
  takePhoto,
  permissionsHook,
}: LabelCaptureScreenProps) {
  const { colors } = useTheme();
  const styles = useMemo(() => makeStyles(colors), [colors]);
  const cameraRef = useRef<CameraView>(null);
  const [phase, setPhase] = useState<Phase>("camera");
  const [photo, setPhoto] = useState<CapturedPhoto | null>(null);
  const [savePhoto, setSavePhoto] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);

  const defaultUpload = useCallback(
    (imageUri: string, save: boolean) =>
      uploadLabelImageApi(session, imageUri, save),
    [session],
  );

  const defaultTakePhoto = useCallback(async (): Promise<CapturedPhoto> => {
    const result = await cameraRef.current?.takePictureAsync({ quality: 0.8 });
    if (!result) {
      throw new Error("Camera is not ready. Please try again.");
    }
    return { uri: result.uri };
  }, []);

  const doTakePhoto = takePhoto ?? defaultTakePhoto;
  const doUpload = upload ?? defaultUpload;

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
      const event = await doUpload(photo.uri, savePhoto);
      onUploaded(event);
    } catch (error) {
      // Error message must not contain image bytes, URIs, or extracted content.
      setUploadError(messageFor(error));
      setPhase("error");
    }
  }, [photo, savePhoto, doUpload, onUploaded]);

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
            accessibilityLabel="Camera viewfinder"
          />

          {/* Overlay controls rendered on top of the viewfinder */}
          <View style={styles.overlay}>
            {(phase === "camera" || phase === "error") && (
              <ShutterControls
                onShutter={() => void handleShutter()}
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

function ShutterControls({
  onShutter,
  error,
  colors,
}: {
  onShutter: () => void;
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
    errorText: {
      color: colors.coral,
      fontSize: 15,
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
      fontSize: 16,
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
      fontSize: 16,
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
      fontSize: 16,
      fontWeight: "600",
    },
    uploadingContainer: {
      alignItems: "center",
      gap: 12,
    },
    uploadingText: {
      // Rendered directly on the live camera feed — fixed white for contrast.
      color: "#FFFFFF",
      fontSize: 16,
      fontWeight: "500",
    },
  });
}
