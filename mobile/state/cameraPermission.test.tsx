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

// ─── Default-hook selection is E2E-gated (FTY-268 permission-mock inertness) ──
//
// `cameraPermission.ts` picks its no-argument default source once at module
// load: the E2E granted stub (FTY-194) under `isE2EMode()`, else expo-camera's
// real `useCameraPermissions`. FTY-268 makes it mandatory to prove that gate is
// inert outside E2E — that `useCameraPermission()`/`CameraCapture` (which pass
// no hook) select REAL permission handling, not the granted stub, when E2E is
// off. We load a fresh module copy under mocked deps for each mode and observe
// which underlying hook the default actually invokes.
describe("useCameraPermission default source is gated on E2E mode", () => {
  const GRANTED: PermissionResponse = {
    status: PermissionStatus.GRANTED,
    granted: true,
    canAskAgain: false,
    expires: "never",
  };
  const UNDETERMINED: PermissionResponse = {
    status: PermissionStatus.UNDETERMINED,
    granted: false,
    canAskAgain: true,
    expires: "never",
  };

  afterEach(() => {
    jest.dontMock("expo-camera");
    jest.dontMock("@/e2e/launchMode");
  });

  // Re-require cameraPermission with expo-camera + launchMode mocked for the
  // given mode, render the no-argument hook (the CameraCapture default), and
  // report which underlying source the module default selected.
  function selectDefaultSource(e2e: boolean): {
    status: CameraPermissionStatus;
    realHook: jest.Mock;
    e2eStub: jest.Mock;
  } {
    let out!: {
      status: CameraPermissionStatus;
      realHook: jest.Mock;
      e2eStub: jest.Mock;
    };
    jest.isolateModules(() => {
      // The real hook reports an OS-driven undetermined state; the E2E stub
      // reports its always-granted response — distinct so the two are
      // distinguishable purely from the surfaced status.
      const realHook = jest.fn(() => [UNDETERMINED, jest.fn(), jest.fn()]);
      const e2eStub = jest.fn(() => [GRANTED, jest.fn(), jest.fn()]);
      jest.doMock("expo-camera", () => ({ useCameraPermissions: realHook }));
      jest.doMock("@/e2e/launchMode", () => ({
        isE2EMode: () => e2e,
        e2eCameraPermissionsHook: e2eStub,
      }));
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const fresh = require("./cameraPermission") as typeof import("./cameraPermission");

      let status: CameraPermissionStatus = "loading";
      function Wrapper() {
        // No hook injected → exercises the module-load default, the same path
        // CameraCapture takes in production.
        status = fresh.useCameraPermission().status;
        return <View />;
      }
      act(() => {
        create(<Wrapper />);
      });
      out = { status, realHook, e2eStub };
    });
    return out;
  }

  it("selects the REAL expo-camera hook — never the E2E granted stub — outside E2E mode", () => {
    const { status, realHook, e2eStub } = selectDefaultSource(false);
    expect(realHook).toHaveBeenCalled();
    expect(e2eStub).not.toHaveBeenCalled();
    // Real permission handling in play: the undetermined OS state is surfaced,
    // proving the mock's auto-granted response was not substituted.
    expect(status).toBe("undetermined");
  });

  it("selects the E2E granted stub only when E2E mode is active", () => {
    const { status, realHook, e2eStub } = selectDefaultSource(true);
    expect(e2eStub).toHaveBeenCalled();
    expect(realHook).not.toHaveBeenCalled();
    expect(status).toBe("granted");
  });
});
