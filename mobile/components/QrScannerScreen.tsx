/**
 * Setup-QR scanner for the connect screen (FTY-107).
 *
 * Reuses the shared camera capture scaffold (`CameraCapture`, FTY-063): the
 * permission gate, rationale, and close plumbing live there; this component only
 * renders the QR-specific camera content. Configured for **QR codes only** —
 * the setup QR carries the server URL, nothing else.
 *
 * Security: the QR payload is **untrusted** and is **not** trusted here — this
 * component only extracts the decoded string and hands it to `onScanned`. The
 * caller (the connect screen) runs the same strict URL validation on it as on a
 * typed address before any network call or persistence, and the scan never
 * carries or stores a secret/token (the setup QR is URL-only by design). The
 * camera stream is ephemeral: no frame, image, or URI is captured or stored.
 */

import { useRef } from "react";
import { StyleSheet, View } from "react-native";
import { CameraView, type BarcodeScanningResult } from "expo-camera";

import {
  CameraCapture,
  type CameraCaptureProps,
} from "@/components/CameraCapture";

const RATIONALE =
  "Slacks uses the camera to scan your server's setup QR so you can connect without typing its address.";

export interface QrScannerScreenProps {
  /**
   * Called with the raw decoded QR string when a code is read. Invoked at most
   * once per mount; the scanner does not re-scan after the first read. The
   * string is untrusted — the caller validates it before using it.
   */
  onScanned: (value: string) => void;
  onClose: () => void;
  /** Injectable for tests; forwarded to `CameraCapture`. */
  permissionsHook?: CameraCaptureProps["permissionsHook"];
}

/**
 * Full-screen QR scanner. Renders a camera view configured for QR codes, calls
 * `onScanned` with the raw decoded string on the first read, then stops.
 */
export function QrScannerScreen({
  onScanned,
  onClose,
  permissionsHook,
}: QrScannerScreenProps) {
  // Mark scanned immediately on the first result so a brief overlap in the
  // native callback queue never fires onScanned twice.
  const scanned = useRef(false);

  const handleScan = (result: BarcodeScanningResult) => {
    if (scanned.current) return;
    scanned.current = true;
    // Only the decoded string is passed — no frame, no image, no URI.
    onScanned(result.data);
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
            onBarcodeScanned={handleScan}
            barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
            accessibilityLabel="Camera viewfinder"
          />
        </View>
      )}
    </CameraCapture>
  );
}
