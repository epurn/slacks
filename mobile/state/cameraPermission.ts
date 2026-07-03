/**
 * Reusable camera permission state for the camera capture scaffold.
 *
 * Wraps expo-camera's `useCameraPermissions` into a compact, testable domain
 * type so the permission state machine is covered independently of rendering.
 * FTY-063 (barcode scanner) and FTY-064 (label-photo capture) share this
 * module; neither hard-codes permission handling into its capture surface.
 *
 * Security: the permission is requested only on first use (when the user opens
 * the capture surface), never at app start. Denial is handled gracefully with
 * no dead end and no repeated nag.
 */

import { useCameraPermissions as useExpoCameraPermissions } from "expo-camera";
import type { PermissionResponse } from "expo";

import { isE2EMode, e2eCameraPermissionsHook } from "@/e2e/launchMode";

/**
 * Camera-permission source used when a consumer does not inject one. In an E2E
 * build this is the granted-permission stub (FTY-194) so the scanner's granted
 * chrome renders on the simulator, which has no camera; otherwise it is
 * expo-camera's real hook. Chosen once at module load — `isE2EMode()` is a
 * compile-time-constant gate, so release builds always get the real hook and
 * Metro dead-code-eliminates the E2E branch.
 */
const defaultPermissionsHook: typeof useExpoCameraPermissions = isE2EMode()
  ? e2eCameraPermissionsHook
  : useExpoCameraPermissions;

export type CameraPermissionStatus =
  | "loading" // OS permission state not yet resolved
  | "undetermined" // user has not been asked yet
  | "granted" // camera access granted
  | "denied" // denied but OS allows asking again (Android; rare on iOS)
  | "blocked"; // denied permanently; user must open system Settings

export interface CameraPermission {
  readonly status: CameraPermissionStatus;
  /** Request camera access from the OS. Resolves after the OS dialog. */
  readonly request: () => Promise<void>;
}

/**
 * Map a raw `PermissionResponse` to our domain status. Exported for unit tests.
 * `null` (not-yet-resolved) maps to `"loading"`.
 */
export function resolvePermissionStatus(
  permission: PermissionResponse | null,
): CameraPermissionStatus {
  if (!permission) return "loading";
  if (permission.granted) return "granted";
  if (permission.status === "undetermined") return "undetermined";
  // denied: canAskAgain=false means iOS permanently blocked (first denial on
  // iOS goes straight here — the OS won't show the dialog a second time).
  return permission.canAskAgain ? "denied" : "blocked";
}

/**
 * Camera permission hook. Wraps `useCameraPermissions` from expo-camera into
 * the compact domain type used by `CameraCapture` and its consumers.
 *
 * @param permissionsHook - Injectable for tests; defaults to
 *   `defaultPermissionsHook` (expo-camera's real hook, or the E2E granted stub
 *   in an E2E build).
 */
export function useCameraPermission(
  permissionsHook: typeof useExpoCameraPermissions = defaultPermissionsHook,
): CameraPermission {
  const [permission, requestPermission] = permissionsHook();

  const request = async () => {
    await requestPermission();
  };

  return { status: resolvePermissionStatus(permission), request };
}
