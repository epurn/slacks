/**
 * Reusable camera capture surface (FTY-063 scaffold, reused by FTY-064).
 *
 * Owns the permission gate so consumers (barcode scanner in FTY-063; label
 * capture in FTY-064) only need to render the camera content specific to their
 * use case. The permission + rationale + close plumbing is shared.
 *
 * States:
 * - loading    — checking OS permission; spinner shown
 * - undetermined — first use; rationale + request button shown before OS dialog
 * - denied     — denied but askable again; request button re-offered
 * - blocked    — permanently denied; "Open Settings" path with no dead end
 * - granted    — camera available; `children` rendered with a close overlay
 *
 * Security: the OS permission is never auto-requested at mount — the user
 * always taps a button first, so our rationale text is visible before the
 * system dialog appears.
 */

import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { openSettings } from "expo-linking";

import {
  useCameraPermission,
  type CameraPermission,
} from "@/state/cameraPermission";
import type { PermissionResponse } from "expo";

export interface CameraCaptureProps {
  onClose: () => void;
  /** Displayed before the OS permission prompt on first use. */
  rationale: string;
  /** Rendered when camera permission is granted. Should fill the surface. */
  children: () => React.ReactNode;
  /**
   * Injectable for tests; defaults to expo-camera's `useCameraPermissions`.
   * Accepts the same signature as expo-camera so tests can pass a mock.
   */
  permissionsHook?: () => [
    PermissionResponse | null,
    () => Promise<PermissionResponse>,
    () => Promise<PermissionResponse>,
  ];
}

/**
 * Permission gate and camera capture surface. Handles all permission states
 * so barcode scanner (FTY-063) and label-photo capture (FTY-064) each only
 * render their camera content.
 */
export function CameraCapture({
  onClose,
  rationale,
  children,
  permissionsHook,
}: CameraCaptureProps) {
  const permission = useCameraPermission(
    permissionsHook as Parameters<typeof useCameraPermission>[0],
  );

  if (permission.status === "loading") {
    return (
      <View style={styles.container}>
        <ActivityIndicator
          accessibilityLabel="Checking camera access"
          color="#FFFFFF"
          size="large"
        />
        <CloseButton onClose={onClose} />
      </View>
    );
  }

  if (permission.status === "granted") {
    return (
      <View style={styles.container}>
        {children()}
        <CloseButton onClose={onClose} />
      </View>
    );
  }

  return (
    <PermissionGate
      permission={permission}
      rationale={rationale}
      onClose={onClose}
    />
  );
}

function PermissionGate({
  permission,
  rationale,
  onClose,
}: {
  permission: CameraPermission;
  rationale: string;
  onClose: () => void;
}) {
  const isBlocked = permission.status === "blocked";

  return (
    <View style={styles.container}>
      <View style={styles.gateContent}>
        <Text
          style={styles.rationaleText}
          accessibilityRole="text"
          accessibilityLabel={
            isBlocked
              ? "Camera access is needed to scan barcodes. You can enable it in Settings."
              : rationale
          }
        >
          {isBlocked
            ? "Camera access is needed to scan barcodes. You can enable it in Settings."
            : rationale}
        </Text>

        {isBlocked ? (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Open Settings"
            onPress={() => void openSettings()}
            style={styles.primaryButton}
          >
            <Text style={styles.primaryButtonLabel}>Open Settings</Text>
          </Pressable>
        ) : (
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="Allow camera access"
            onPress={() => void permission.request()}
            style={styles.primaryButton}
          >
            <Text style={styles.primaryButtonLabel}>Allow Camera Access</Text>
          </Pressable>
        )}
      </View>
      <CloseButton onClose={onClose} />
    </View>
  );
}

function CloseButton({ onClose }: { onClose: () => void }) {
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel="Close scanner"
      onPress={onClose}
      style={styles.closeButton}
    >
      <Text style={styles.closeButtonLabel} aria-hidden>
        ✕
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#000000",
    alignItems: "center",
    justifyContent: "center",
  },
  gateContent: {
    alignItems: "center",
    paddingHorizontal: 32,
  },
  rationaleText: {
    color: "#FFFFFF",
    fontSize: 17,
    textAlign: "center",
    marginBottom: 24,
    lineHeight: 24,
  },
  primaryButton: {
    backgroundColor: "#0A84FF",
    borderRadius: 10,
    paddingVertical: 14,
    paddingHorizontal: 28,
    alignItems: "center",
    minHeight: 44,
    justifyContent: "center",
  },
  primaryButtonLabel: {
    color: "#FFFFFF",
    fontSize: 16,
    fontWeight: "600",
  },
  closeButton: {
    position: "absolute",
    top: 60,
    right: 20,
    width: 36,
    height: 36,
    borderRadius: 18,
    backgroundColor: "rgba(0,0,0,0.6)",
    alignItems: "center",
    justifyContent: "center",
    minWidth: 44,
    minHeight: 44,
  },
  closeButtonLabel: {
    color: "#FFFFFF",
    fontSize: 18,
    fontWeight: "600",
  },
});
