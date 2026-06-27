/**
 * Tests for the camera permission state machine (FTY-063).
 *
 * The pure mapping logic is tested directly; the hook wiring is tested through
 * a minimal wrapper component, mirroring the react-test-renderer style used in
 * the rest of the mobile test suite.
 */

import { act, create } from "react-test-renderer";
import React from "react";
import { View } from "react-native";
import { PermissionStatus } from "expo";

import {
  resolvePermissionStatus,
  useCameraPermission,
  type CameraPermissionStatus,
} from "./cameraPermission";
import type { PermissionResponse } from "expo";

function makePermission(overrides: Partial<PermissionResponse>): PermissionResponse {
  return {
    status: PermissionStatus.UNDETERMINED,
    granted: false,
    canAskAgain: true,
    expires: "never",
    ...overrides,
  };
}

// ─── Pure mapping function ──────────────────────────────────────────────────

describe("resolvePermissionStatus", () => {
  it("returns loading for null (OS not yet queried)", () => {
    expect(resolvePermissionStatus(null)).toBe("loading");
  });

  it("returns undetermined when the user has not been asked yet", () => {
    expect(
      resolvePermissionStatus(
        makePermission({ status: PermissionStatus.UNDETERMINED, granted: false }),
      ),
    ).toBe("undetermined");
  });

  it("returns granted when camera access is granted", () => {
    expect(
      resolvePermissionStatus(
        makePermission({ status: PermissionStatus.GRANTED, granted: true }),
      ),
    ).toBe("granted");
  });

  it("returns blocked when denied with canAskAgain=false (permanent denial on iOS)", () => {
    expect(
      resolvePermissionStatus(
        makePermission({
          status: PermissionStatus.DENIED,
          granted: false,
          canAskAgain: false,
        }),
      ),
    ).toBe("blocked");
  });

  it("returns denied when denied but canAskAgain=true (Android re-ask path)", () => {
    expect(
      resolvePermissionStatus(
        makePermission({
          status: PermissionStatus.DENIED,
          granted: false,
          canAskAgain: true,
        }),
      ),
    ).toBe("denied");
  });
});

// ─── Hook wiring ─────────────────────────────────────────────────────────────

describe("useCameraPermission", () => {
  it("request() calls the underlying requestPermission function", async () => {
    const requestPermission = jest
      .fn()
      .mockResolvedValue(
        makePermission({ status: PermissionStatus.GRANTED, granted: true }),
      );
    const permission = makePermission({
      status: PermissionStatus.UNDETERMINED,
      granted: false,
    });
    const hook = jest.fn().mockReturnValue([permission, requestPermission, jest.fn()]);

    let capturedStatus: CameraPermissionStatus = "loading";
    let capturedRequest!: () => Promise<void>;

    function Wrapper() {
      const cam = useCameraPermission(hook);
      capturedStatus = cam.status;
      capturedRequest = cam.request;
      return <View />;
    }

    act(() => {
      create(<Wrapper />);
    });

    expect(capturedStatus).toBe("undetermined");

    await act(async () => {
      await capturedRequest();
    });

    expect(requestPermission).toHaveBeenCalledTimes(1);
  });
});
