/**
 * Barcode scanner screen (FTY-063, scan chrome added in FTY-194).
 *
 * First consumer of the shared camera capture scaffold (`CameraCapture`). The
 * permission gate and close plumbing live in `CameraCapture`; this component
 * renders the barcode-specific camera content: a live feed plus the scan chrome
 * — a viewfinder reticle, "Point at a barcode" guidance, a torch toggle for low
 * light, and a "Type it instead" manual fallback so a failed or unsupported scan
 * is never a dead end (FTY-194, "Acknowledge every action" / never a dead end).
 *
 * On a successful read, `onBarcodeScanned` is called with the raw barcode
 * string exactly once. The camera stream is treated as ephemeral: only the
 * string value is extracted; no frames or images are stored on device or sent
 * anywhere. The caller (TodayScreen) is responsible for submitting that string
 * through the existing log-events create path (FTY-030) so the backend
 * FTY-060 pipeline resolves it.
 *
 * The "Type it instead" affordance carries no scan data: it calls `onManualEntry`
 * so the host dismisses the scanner and lands the user in the Today composer,
 * pre-filled with an editable starter and focused, to type the product — never
 * any partial/failed scan bytes.
 *
 * Security: camera stream ephemeral — no frames, no images, no URIs are
 * captured or sent. Only the barcode string passes through `onBarcodeScanned`.
 */

import { useRef, useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { CameraView, type BarcodeScanningResult } from "expo-camera";

import { AppIcon } from "@/components/ui";
import { CameraCapture, type CameraCaptureProps } from "@/components/CameraCapture";

const RATIONALE =
  "Fatty uses the camera to scan product barcodes so you can log packaged foods quickly.";

/** Guidance copy shown over the live feed so the user knows what to do. */
const GUIDANCE = "Point at a barcode";

/** Barcode types relevant for packaged food products. */
const FOOD_BARCODE_TYPES = [
  "ean13",
  "ean8",
  "upc_a",
  "upc_e",
  "qr",
] as const;

export interface BarcodeScannerScreenProps {
  /**
   * Called with the raw barcode string when a barcode is successfully read.
   * Invoked at most once per mount; the scanner does not re-scan after the
   * first successful read.
   */
  onBarcodeScanned: (barcode: string) => void;
  onClose: () => void;
  /**
   * The never-a-dead-end escape hatch: called when the user taps "Type it
   * instead". The host dismisses the scanner and focuses the Today composer so
   * the user can type the product. Carries no scan data.
   */
  onManualEntry: () => void;
  /**
   * Injectable for tests; forwarded to `CameraCapture`.
   */
  permissionsHook?: CameraCaptureProps["permissionsHook"];
}

/**
 * Full-screen barcode scanner. Renders a camera view configured for barcode
 * scanning with a reticle/guidance/torch overlay, calls `onBarcodeScanned` with
 * the raw barcode string on success, then stops scanning. Use inside a Modal
 * from TodayScreen.
 */
export function BarcodeScannerScreen({
  onBarcodeScanned,
  onClose,
  onManualEntry,
  permissionsHook,
}: BarcodeScannerScreenProps) {
  const insets = useSafeAreaInsets();
  // Prevent double-fire: mark scanned immediately on the first result so a
  // brief overlap in the native callback queue never calls onBarcodeScanned twice.
  const scanned = useRef(false);
  // Torch is off by default; the user opts in for low light.
  const [torchOn, setTorchOn] = useState(false);

  const handleBarcodeScan = (result: BarcodeScanningResult) => {
    if (scanned.current) return;
    scanned.current = true;
    // Only the barcode string is passed — no frame, no image, no URI.
    onBarcodeScanned(result.data);
  };

  return (
    <CameraCapture
      onClose={onClose}
      rationale={RATIONALE}
      permissionsHook={permissionsHook}
    >
      {() => (
        <View
          style={StyleSheet.absoluteFill}
          accessibilityLabel="Camera scanner active"
        >
          <CameraView
            style={StyleSheet.absoluteFill}
            facing="back"
            enableTorch={torchOn}
            onBarcodeScanned={handleBarcodeScan}
            barcodeScannerSettings={{
              barcodeTypes: [...FOOD_BARCODE_TYPES],
            }}
            accessibilityLabel="Camera viewfinder"
          />

          {/* Viewfinder reticle + guidance copy, centred over the feed. Purely
              informational, so it never intercepts touches. */}
          <View style={styles.scanArea} pointerEvents="none">
            <View style={styles.reticle} testID="barcode-reticle" />
            <Text
              style={styles.guidance}
              accessibilityRole="text"
              accessibilityLabel={GUIDANCE}
            >
              {GUIDANCE}
            </Text>
          </View>

          {/* Torch toggle (top-left; the close control sits top-right). */}
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Torch"
            accessibilityHint="Toggles the flashlight to scan in low light"
            accessibilityState={{ selected: torchOn }}
            onPress={() => setTorchOn((prev) => !prev)}
            style={styles.torchButton}
          >
            <AppIcon
              name={torchOn ? "bolt.fill" : "bolt.slash.fill"}
              size={20}
              color="#FFFFFF"
            />
          </Pressable>

          {/* "Type it instead" — the never-a-dead-end path to the composer. */}
          <View
            style={[styles.manualArea, { bottom: insets.bottom + 32 }]}
            pointerEvents="box-none"
          >
            <Pressable
              accessibilityRole="button"
              accessibilityLabel="Type it instead"
              accessibilityHint="Closes the scanner and opens the composer to type the product"
              onPress={onManualEntry}
              style={styles.manualButton}
            >
              <AppIcon name="keyboard" size={20} color="#FFFFFF" />
              <Text style={styles.manualLabel}>Type it instead</Text>
            </Pressable>
          </View>
        </View>
      )}
    </CameraCapture>
  );
}

const styles = StyleSheet.create({
  // Overlay chrome sits on the live camera feed, not a themed surface — fixed
  // white / translucent-dark for contrast in both light and dark, matching the
  // label-capture overlay convention.
  scanArea: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    alignItems: "center",
    justifyContent: "center",
    gap: 20,
  },
  reticle: {
    width: "78%",
    aspectRatio: 1.7,
    borderWidth: 3,
    borderColor: "rgba(255,255,255,0.9)",
    borderRadius: 16,
  },
  guidance: {
    color: "#FFFFFF",
    fontSize: 16,
    fontWeight: "500",
    textAlign: "center",
    backgroundColor: "rgba(0,0,0,0.5)",
    borderRadius: 8,
    paddingHorizontal: 16,
    paddingVertical: 8,
    overflow: "hidden",
  },
  torchButton: {
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
  manualArea: {
    position: "absolute",
    left: 0,
    right: 0,
    alignItems: "center",
  },
  manualButton: {
    flexDirection: "row",
    alignItems: "center",
    gap: 8,
    backgroundColor: "rgba(0,0,0,0.6)",
    borderRadius: 22,
    paddingHorizontal: 20,
    paddingVertical: 12,
    minHeight: 44,
  },
  manualLabel: {
    color: "#FFFFFF",
    fontSize: 16,
    fontWeight: "600",
  },
});
