/**
 * `useLabelProposal` visual-review seam tests (FTY-262 + FTY-394).
 *
 * The confirm-parsed-values sheet's in-modal settled marker (FTY-262/FTY-270)
 * must render for BOTH confirm-parsed-family presets — `today.confirm_parsed`
 * and `capture.confirm_parsed` (FTY-268) — since both open the same sheet, and
 * it must emit the *active* preset's `visual-review-settled:<preset>` id so the
 * committed smoke flow's `capture.confirm_parsed` step can reach it on a real
 * simulator (FTY-394).
 *
 * These render the hook in isolation (no TodayScreen), driving the visual-review
 * session directly, and prove:
 *   - the marker emits the active family preset's id, on the same network-quiet
 *     settle gate, for each family;
 *   - each family keeps its own seeding path — `today` seeds the initial
 *     proposal here, `capture` does NOT (it seeds via `useTodayData`'s
 *     `handleLabelUploaded`), so the hook never double-seeds the capture family;
 *   - the marker + seeding are inert outside `isE2EMode()`.
 */

import { act, create, type ReactTestRenderer } from "react-test-renderer";

import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import { getDailySummary as getDailySummaryApi } from "@/api/dailySummary";
import { getLabelProposal as getLabelProposalApi } from "@/api/labelProposal";
import {
  activateVisualReviewPreset,
  __deactivateVisualReview,
} from "@/e2e/visualReview/session";
import { QUIET_MS } from "@/e2e/visualReview/VisualReviewSettleOverlay";

import {
  CAPTURE_BARCODE_GRANTED_PRESET,
  CAPTURE_CONFIRM_PARSED_PRESET,
} from "./captureVisualReview";
import { useLabelProposal } from "./useLabelProposal";
import {
  CONFIRM_PARSED_ITEM,
  CONFIRM_PARSED_PRESET_NAME,
} from "./visualReviewConfirmParsed";

type HookResult = ReturnType<typeof useLabelProposal>;

const noopSetter = () => {};

function Harness({ onRender }: { onRender: (r: HookResult) => void }): null {
  const result = useLabelProposal({
    apiSession: null,
    getLabelProposal: getLabelProposalApi,
    getDailySummary: getDailySummaryApi,
    setEvents: noopSetter,
    setItemsByEvent: noopSetter,
    setSummary: noopSetter,
    setSummaryError: noopSetter,
    setLabelCaptureOpen: noopSetter,
  });
  onRender(result);
  return null;
}

let latest: HookResult;
let renderer: ReactTestRenderer | null = null;

function mountHook(): ReactTestRenderer {
  act(() => {
    renderer = create(
      <Harness
        onRender={(r) => {
          latest = r;
        }}
      />,
    );
  });
  return renderer!;
}

const gThis = globalThis as Record<string, unknown>;
const ORIGINAL_DEV = gThis["__DEV__"] as boolean;
const ORIGINAL_E2E_ENV = process.env.EXPO_PUBLIC_SLACKS_E2E;

function setE2E(on: boolean): void {
  gThis["__DEV__"] = on;
  if (on) {
    process.env["EXPO_PUBLIC_SLACKS_E2E"] = "true";
  } else {
    delete process.env["EXPO_PUBLIC_SLACKS_E2E"];
  }
}

/** Advance virtual time past the network-quiet settle window and flush. */
async function settle(): Promise<void> {
  await act(async () => {
    jest.advanceTimersByTime(QUIET_MS + 50);
    await Promise.resolve();
  });
}

beforeEach(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  act(() => {
    renderer?.unmount();
    __deactivateVisualReview();
  });
  renderer = null;
  jest.useRealTimers();
  gThis["__DEV__"] = ORIGINAL_DEV;
  if (ORIGINAL_E2E_ENV === undefined) {
    delete process.env["EXPO_PUBLIC_SLACKS_E2E"];
  } else {
    process.env["EXPO_PUBLIC_SLACKS_E2E"] = ORIGINAL_E2E_ENV;
  }
});

describe("useLabelProposal confirm-parsed settled marker (FTY-394)", () => {
  it("emits visual-review-settled:today.confirm_parsed for the today family, on the network-quiet gate", async () => {
    setE2E(true);
    act(() => {
      activateVisualReviewPreset(CONFIRM_PARSED_PRESET_NAME, null);
    });

    mountHook();

    // Not emitted on the mid-load frame — only after the quiet window elapses.
    expect(latest.labelProposalSettledMarker).toBeNull();
    await settle();
    expect(latest.labelProposalSettledMarker).toBe(
      `visual-review-settled:${CONFIRM_PARSED_PRESET_NAME}`,
    );
  });

  it("emits visual-review-settled:capture.confirm_parsed for the capture family (FTY-268), same gate", async () => {
    setE2E(true);
    act(() => {
      activateVisualReviewPreset(CAPTURE_CONFIRM_PARSED_PRESET, null);
    });

    mountHook();

    expect(latest.labelProposalSettledMarker).toBeNull();
    await settle();
    expect(latest.labelProposalSettledMarker).toBe(
      `visual-review-settled:${CAPTURE_CONFIRM_PARSED_PRESET}`,
    );
  });

  it("emits no marker for a non-confirm-parsed preset (e.g. capture.barcode_granted)", async () => {
    setE2E(true);
    act(() => {
      activateVisualReviewPreset(CAPTURE_BARCODE_GRANTED_PRESET, null);
    });

    mountHook();
    await settle();
    expect(latest.labelProposalSettledMarker).toBeNull();
  });

  it("is inert outside isE2EMode() even if the capture preset were somehow active", async () => {
    setE2E(false);
    act(() => {
      activateVisualReviewPreset(CAPTURE_CONFIRM_PARSED_PRESET, null);
    });

    mountHook();
    await settle();
    expect(latest.labelProposalSettledMarker).toBeNull();
  });
});

describe("useLabelProposal proposal seeding stays per-family (no double-seed)", () => {
  it("seeds the initial proposal from the initial-state seam for today.confirm_parsed", () => {
    setE2E(true);
    act(() => {
      activateVisualReviewPreset(CONFIRM_PARSED_PRESET_NAME, null);
    });

    mountHook();

    // today.confirm_parsed opens the sheet from the initial-state seam here.
    expect(latest.labelProposal).toEqual<DerivedFoodItemDTO>(CONFIRM_PARSED_ITEM);
    expect(latest.labelProposalVisible).toBe(true);
  });

  it("does NOT seed the initial proposal for capture.confirm_parsed (it seeds via useTodayData's handleLabelUploaded)", () => {
    setE2E(true);
    act(() => {
      activateVisualReviewPreset(CAPTURE_CONFIRM_PARSED_PRESET, null);
    });

    mountHook();

    // The capture family must NOT double-seed: the sheet stays closed until
    // useTodayData drives handleLabelUploaded (exercised in TodayScreenCapture).
    expect(latest.labelProposal).toBeNull();
    expect(latest.labelProposalVisible).toBe(false);
  });

  it("does not seed for the today family outside isE2EMode()", () => {
    setE2E(false);
    act(() => {
      activateVisualReviewPreset(CONFIRM_PARSED_PRESET_NAME, null);
    });

    mountHook();

    expect(latest.labelProposal).toBeNull();
    expect(latest.labelProposalVisible).toBe(false);
  });
});
