/**
 * Barcode scanner screen (FTY-063).
 *
 * First consumer of the shared camera capture scaffold (`CameraCapture`). The
 * permission gate and close plumbing live in `CameraCapture`; this component
 * only renders the barcode-specific camera content.
 *
 * On a successful read, `onBarcodeScanned` is called with the raw barcode
 * string exactly once. The camera stream is treated as ephemeral: only the
 * string value is extracted; no frames or images are stored on device or sent
 * anywhere. The caller (TodayScreen) is responsible for submitting that string
 * through the existing log-events create path (FTY-030) so the backend
 * FTY-060 pipeline resolves it.
 *
 * Security: camera stream ephemeral — no frames, no images, no URIs are
 * captured or sent. Only the barcode string passes through `onBarcodeScanned`.
 */

import { useRef } from "react";
import { StyleSheet, View } from "react-native";
import { CameraView, type BarcodeScanningResult } from "expo-camera";

import { CameraCapture, type CameraCaptureProps } from "@/components/CameraCapture";

const RATIONALE =
  "Fatty uses the camera to scan product barcodes so you can log packaged foods quickly.";

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
   * Injectable for tests; forwarded to `CameraCapture`.
   */
  permissionsHook?: CameraCaptureProps["permissionsHook"];
}

/**
 * Full-screen barcode scanner. Renders a camera view configured for barcode
 * scanning, calls `onBarcodeScanned` with the raw barcode string on success,
 * then stops scanning. Use inside a Modal from TodayScreen.
 */
export function BarcodeScannerScreen({
  onBarcodeScanned,
  onClose,
  permissionsHook,
}: BarcodeScannerScreenProps) {
  // Prevent double-fire: mark scanned immediately on the first result so a
  // brief overlap in the native callback queue never calls onBarcodeScanned twice.
  const scanned = useRef(false);

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
            onBarcodeScanned={handleBarcodeScan}
            barcodeScannerSettings={{
              barcodeTypes: [...FOOD_BARCODE_TYPES],
            }}
            accessibilityLabel="Camera viewfinder"
          />
        </View>
      )}
    </CameraCapture>
  );
}
