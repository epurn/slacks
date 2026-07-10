/**
 * `today.confirm_parsed` visual-review seam tests (FTY-262).
 *
 * Proves the E2E-only initial-state seam `useLabelProposal` reads
 * (`visualReviewConfirmParsed.ts` + the seam in `useLabelProposal.ts`):
 *   - the preset is registered through FTY-247's registration API (reachable by
 *     name, without this story touching the shared registry/manifest),
 *   - activating it opens Today's parsed-confirmation sub-state from the very
 *     first render — no "Capture label" / "Take photo" / "Upload label" taps,
 *   - it is inert outside `isE2EMode()` even if the runtime preset state were
 *     somehow set without going through the gated deep-link route,
 *   - it never perturbs the default Today flow when no preset is active.
 */

import { act, type ReactTestRenderer } from "react-test-renderer";

import { TodayScreen } from "@/components/TodayScreen";
import { mockReduceMotion } from "@/testUtils/reduceMotion";
import {
  activateVisualReviewPreset,
  __deactivateVisualReview,
} from "@/e2e/visualReview/session";
import { getVisualReviewPreset } from "@/e2e/visualReview";
import { QUIET_MS } from "@/e2e/visualReview/VisualReviewSettleOverlay";

import { CONFIRM_PARSED_PRESET_NAME } from "./visualReviewConfirmParsed";
import {
  INACTIVE,
  SESSION,
  cleanupTrees,
  hasA11yLabel,
  mount,
  textContent,
} from "./todayTestUtils";

jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactNative = require("react-native");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  return {
    SymbolView: ({ name, accessibilityLabel }: { name: string; accessibilityLabel?: string }) =>
      ReactLib.createElement(ReactNative.View, {
        testID: `sf-symbol-${String(name)}`,
        accessibilityLabel,
      }),
  };
});

jest.mock("expo-camera", () => ({
  useCameraPermissions: jest.fn(() => [
    { status: "granted", granted: true, canAskAgain: false, expires: "never" },
    jest.fn().mockResolvedValue({ status: "granted", granted: true }),
    jest.fn().mockResolvedValue({ status: "granted", granted: true }),
  ]),
  CameraView: jest.fn(() => null),
}));

jest.mock("expo-linking", () => ({
  openSettings: jest.fn().mockResolvedValue(undefined),
}));

const gThis = globalThis as Record<string, unknown>;
const ORIGINAL_DEV = gThis["__DEV__"] as boolean;
const ORIGINAL_E2E_ENV = process.env.EXPO_PUBLIC_FATTY_E2E;

function setE2E(on: boolean): void {
  gThis["__DEV__"] = on;
  if (on) {
    process.env["EXPO_PUBLIC_FATTY_E2E"] = "true";
  } else {
    delete process.env["EXPO_PUBLIC_FATTY_E2E"];
  }
}

function mountToday(): ReactTestRenderer {
  return mount(
    <TodayScreen
      session={SESSION}
      load={jest.fn().mockResolvedValue([])}
      loadEntries={jest.fn().mockResolvedValue([])}
      useActive={INACTIVE}
    />,
  );
}

beforeEach(() => mockReduceMotion(false));

afterEach(() => {
  cleanupTrees();
  __deactivateVisualReview();
  gThis["__DEV__"] = ORIGINAL_DEV;
  if (ORIGINAL_E2E_ENV === undefined) {
    delete process.env["EXPO_PUBLIC_FATTY_E2E"];
  } else {
    process.env["EXPO_PUBLIC_FATTY_E2E"] = ORIGINAL_E2E_ENV;
  }
});

describe("today.confirm_parsed visual-review preset", () => {
  it("is registered through the FTY-247 registration API with the Today route/settled path", () => {
    const preset = getVisualReviewPreset(CONFIRM_PARSED_PRESET_NAME);
    expect(preset).toBeDefined();
    expect(preset?.route).toBe("/");
    expect(preset?.settledPath).toBe("/");
  });

  it("reaches the parsed-confirmation sub-state via the initial-state seam — no scripted taps", async () => {
    // The settled marker's QUIET_MS window is driven by a real setTimeout in
    // VisualReviewSettleMarker. Fake timers let the test assert the
    // absent-before/present-after transition at controlled points in virtual
    // time instead of racing the host scheduler under load (flake fixed by
    // FTY-318 — see the pre-fix `:127` failure this guards against).
    jest.useFakeTimers();
    try {
      setE2E(true);
      activateVisualReviewPreset(CONFIRM_PARSED_PRESET_NAME, null);

      const tree = mountToday();
      await act(async () => {
        await Promise.resolve();
      });

      // The confirm-parsed-values sheet is open from the first render: its
      // parsed values, "not yet counted" state, and provenance are visible
      // without ever pressing "Capture label" / "Take photo" / "Upload label".
      expect(textContent(tree)).toContain("Granola bar");
      expect(hasA11yLabel(tree, "Looks right, add it")).toBe(true);

      const marker = `visual-review-settled:${CONFIRM_PARSED_PRESET_NAME}`;

      // FTY-262 fix: the settled marker respects FTY-247's network-quiet settle
      // contract — it is NOT emitted on the mid-load frame (the sheet merely
      // mounting), so screenshot automation cannot capture a mid-load/"Refreshing…"
      // frame. It stays absent until the QUIET_MS window elapses. No virtual
      // time has been advanced yet, so this is asserted before any quiet time
      // has passed.
      expect(hasA11yLabel(tree, marker)).toBe(false);

      // Once the network goes quiet the sheet exposes the marker inside its own
      // modal (accessibilityViewIsModal hides the shared navigator-level
      // VisualReviewSettleOverlay while it is presented), under the exact same
      // `visual-review-settled:<preset>` convention Maestro waits on. Advance
      // virtual time past the settle window and flush the resulting state
      // update.
      await act(async () => {
        jest.advanceTimersByTime(QUIET_MS + 50);
        await Promise.resolve();
      });
      expect(hasA11yLabel(tree, marker)).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });

  it("is inert outside isE2EMode() even if the runtime preset were somehow already active", async () => {
    setE2E(false);
    // Simulate the runtime state being set without going through the
    // isE2EMode()-gated deep-link route (app/__visual-review.tsx) — the seam's
    // own isE2EMode() check, not just the route's gate, must keep this inert.
    activateVisualReviewPreset(CONFIRM_PARSED_PRESET_NAME, null);

    const tree = mountToday();
    await act(async () => {});

    expect(textContent(tree)).not.toContain("Granola bar");
    expect(hasA11yLabel(tree, "Looks right, add it")).toBe(false);
    expect(
      hasA11yLabel(tree, `visual-review-settled:${CONFIRM_PARSED_PRESET_NAME}`),
    ).toBe(false);
  });

  it("does not perturb the default Today flow when no preset is active", async () => {
    setE2E(true);
    // No activateVisualReviewPreset call — the default, non-preset E2E state.

    const tree = mountToday();
    await act(async () => {});

    expect(textContent(tree)).not.toContain("Granola bar");
    expect(hasA11yLabel(tree, "Looks right, add it")).toBe(false);
    expect(
      hasA11yLabel(tree, `visual-review-settled:${CONFIRM_PARSED_PRESET_NAME}`),
    ).toBe(false);
  });
});
