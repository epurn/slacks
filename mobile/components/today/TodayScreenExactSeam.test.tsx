import { act } from "react-test-renderer";

import { TodayScreen } from "@/components/TodayScreen";
import { __deactivateVisualReview } from "@/e2e/visualReview/session";
import { activateVisualReviewPreset } from "@/e2e/visualReview";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

import {
  INACTIVE,
  SESSION,
  cleanupTrees,
  hasA11yLabel,
  mount,
  press,
  textContent,
} from "./todayTestUtils";

/**
 * FTY-313: the `Make it exact` exact-evidence audit presets. The sub-flow's
 * choice / preview / error / label-open states are component-local state inside
 * the correction sheet with no route param or tap-free entry point — and at the
 * make-exact sheet's dimmed detent iOS exposes no in-modal content to a scripted
 * tap (FTY-272). This suite proves the E2E-only visual-review seam
 * (`components/correction/visualReviewSeam.ts`) opens each state directly over
 * the low-trust synthetic entry, never via a scripted row tap — the same data
 * the Maestro flow screenshots.
 *
 * Importing `TodayScreen` pulls in `useTodayData` → `visualReviewSeam`, whose
 * module-load side effect registers the presets.
 */

jest.mock("@/theme/haptics", () => ({
  entryResolvedHaptic: jest.fn(),
  correctionSavedHaptic: jest.fn(),
  targetReachedHaptic: jest.fn(),
}));

jest.mock("@/api/logEvents", () => {
  const actual = jest.requireActual("@/api/logEvents");
  return {
    ...actual,
    listTodayLogEventEntries: jest.fn().mockResolvedValue([]),
  };
});

// expo-camera: granted permission + a CameraView stub so the FTY-311 label
// capture surface (opened from the exact flow by `correction.exact_label`)
// renders inside its modal on the camera-less test renderer.
jest.mock("expo-camera", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require("react-native");
  return {
    useCameraPermissions: jest.fn(() => [
      { status: "granted", granted: true, canAskAgain: false, expires: "never" },
      jest.fn().mockResolvedValue({ status: "granted", granted: true }),
      jest.fn().mockResolvedValue({ status: "granted", granted: true }),
    ]),
    CameraView: jest.fn().mockImplementation((props: Record<string, unknown>) =>
      ReactLib.createElement(View, { ...props, testID: "camera-view" }),
    ),
  };
});

jest.mock("expo-linking", () => ({ openSettings: jest.fn().mockResolvedValue(undefined) }));

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

/** Mount TodayScreen with the given preset active and let its effects settle. */
async function mountWithPreset(name: string) {
  setE2E(true);
  activateVisualReviewPreset(name, null);
  const load = jest.fn().mockResolvedValue([]);
  const tree = mount(<TodayScreen session={SESSION} load={load} useActive={INACTIVE} />);
  await act(async () => {});
  return tree;
}

beforeEach(() => mockReduceMotion(false));

afterEach(() => {
  cleanupTrees();
  __deactivateVisualReview();
  gThis["__DEV__"] = ORIGINAL_DEV;
  if (ORIGINAL_E2E_ENV === undefined) {
    delete process.env["EXPO_PUBLIC_SLACKS_E2E"];
  } else {
    process.env["EXPO_PUBLIC_SLACKS_E2E"] = ORIGINAL_E2E_ENV;
  }
});

describe("Make it exact visual-review seam (FTY-313)", () => {
  it("exact_eligible: the Make it exact nudge is visible on a low-trust item", async () => {
    const tree = await mountWithPreset("correction.exact_eligible");
    expect(hasA11yLabel(tree, "Make it exact")).toBe(true);
    expect(hasA11yLabel(tree, "visual-review-settled:correction.exact_eligible")).toBe(true);
  });

  it("exact_applied: the nudge is gone and the source is now Open Food Facts", async () => {
    const tree = await mountWithPreset("correction.exact_applied");
    // Applied end state: source-backed, so the exact-upgrade nudge is hidden.
    expect(hasA11yLabel(tree, "Make it exact")).toBe(false);
    expect(textContent(tree)).toContain("Open Food Facts");
  });

  it("exact_choose: the choice surface offers scan / type / label / cancel", async () => {
    const tree = await mountWithPreset("correction.exact_choose");
    expect(hasA11yLabel(tree, "Scan barcode")).toBe(true);
    expect(hasA11yLabel(tree, "Type barcode")).toBe(true);
    expect(hasA11yLabel(tree, "Capture nutrition label")).toBe(true);
    expect(hasA11yLabel(tree, "Cancel make it exact")).toBe(true);
    expect(hasA11yLabel(tree, "visual-review-settled:correction.exact_choose")).toBe(true);
  });

  it("exact_barcode_exact: the exact proposal preview is applyable", async () => {
    const tree = await mountWithPreset("correction.exact_barcode_exact");
    expect(hasA11yLabel(tree, "Exact match from Open Food Facts")).toBe(true);
    expect(hasA11yLabel(tree, "Apply")).toBe(true);
    expect(hasA11yLabel(tree, "visual-review-settled:correction.exact_barcode_exact")).toBe(true);
  });

  it("exact_barcode_fallback: the fallback preview reads as rough, never exact", async () => {
    const tree = await mountWithPreset("correction.exact_barcode_fallback");
    expect(hasA11yLabel(tree, "Rough fallback — exact evidence wasn't found")).toBe(true);
    expect(textContent(tree)).toContain("This is the best rough fallback");
    // The fallback is never mislabelled as an exact match.
    expect(hasA11yLabel(tree, "Exact match from Open Food Facts")).toBe(false);
  });

  it("exact_no_proposal: the error state is calm and actionable", async () => {
    const tree = await mountWithPreset("correction.exact_no_proposal");
    expect(hasA11yLabel(tree, "Try again")).toBe(true);
    expect(hasA11yLabel(tree, "Change match")).toBe(true);
    expect(hasA11yLabel(tree, "Manual edit")).toBe(true);
    expect(textContent(tree)).toContain("no rough fallback either");
  });

  it("exact_label: the label capture opens from the flow; save-photo defaults off", async () => {
    const tree = await mountWithPreset("correction.exact_label");
    // The label capture surface is presented from the correction flow.
    expect(hasA11yLabel(tree, "Take photo")).toBe(true);
    // The injected takePhoto seam lets the shutter reach the save-photo preview.
    await act(async () => press(tree, "Take photo"));
    const saveSwitch = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Save this photo" &&
        typeof n.props.onValueChange === "function",
    );
    expect(saveSwitch.props.value).toBe(false);
  });

  it("is inert outside E2E mode: no exact sheet auto-opens", async () => {
    setE2E(false);
    activateVisualReviewPreset("correction.exact_choose", null);
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(<TodayScreen session={SESSION} load={load} useActive={INACTIVE} />);
    await act(async () => {});
    // "Cancel make it exact" is unique to the exact panel (unlike "Scan barcode",
    // which the Today composer also carries), so its absence proves no sheet opened.
    expect(hasA11yLabel(tree, "Cancel make it exact")).toBe(false);
    expect(hasA11yLabel(tree, "Make it exact")).toBe(false);
    expect(hasA11yLabel(tree, "visual-review-settled:correction.exact_choose")).toBe(false);
  });
});
