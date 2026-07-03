import { StyleSheet } from "react-native";
import { act } from "react-test-renderer";

import { TodayScreen } from "./TodayScreen";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

import {
  INACTIVE,
  SESSION,
  cleanupTrees,
  event,
  mount,
} from "./today/todayTestUtils";

jest.mock("@/theme/haptics", () => ({
  entryResolvedHaptic: jest.fn(),
  correctionSavedHaptic: jest.fn(),
  targetReachedHaptic: jest.fn(),
}));

jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactNative = require("react-native");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  return {
    SymbolView: ({ name }: { name: string }) =>
      ReactLib.createElement(ReactNative.View, {
        testID: `sf-symbol-${String(name)}`,
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

jest.mock("@/api/logEvents", () => {
  const actual = jest.requireActual("@/api/logEvents");
  return {
    ...actual,
    listTodayLogEventEntries: jest.fn().mockResolvedValue([]),
  };
});

beforeEach(() => mockReduceMotion(false));

afterEach(cleanupTrees);

// The FTY-185 occlusion contract has two halves. `_layout.test.tsx` proves the
// first: the tab bar is a real, full-footprint expo-blur `.ultraThin` overlay
// (position:absolute, transparent background, BlurView `absoluteFill` at
// intensity 100). This suite proves the second: the Today timeline actually
// scrolls *beneath* that overlay. Together they are the structural proof that
// scrolled content is dimmed/occluded under the bar rather than reading fully
// legible through the labels — the part machine-assertable in the JS harness.
// (True pixel-level legibility through a native blur is not observable in Jest
// or Maestro; the accessibility tree carries no rendered pixels.)
describe("TodayScreen tab-bar occlusion clearance (FTY-185)", () => {
  it("reserves bottom clearance so timeline content scrolls beneath the floating tab bar", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "Oatmeal", status: "completed" }),
      ]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    const scroll = tree.root.find((n) => n.props.testID === "today-screen");
    const contentStyle = StyleSheet.flatten(
      scroll.props.contentContainerStyle,
    ) as { paddingBottom?: number };

    // The safe-area bottom inset seeded by the test SafeAreaProvider metrics
    // (see `mount` in todayTestUtils).
    const safeAreaBottom = 34;
    // The tab bar floats over the scroll content (position:absolute in
    // _layout.tsx), so the content container must reserve clearance *beyond*
    // the safe area for the bar's whole footprint. Without that surplus the
    // last timeline row would sit permanently trapped behind the occluding bar
    // instead of scrolling clear of it — the content-under-tab-bar requirement.
    // A standard iOS tab bar is ~49pt tall; require at least that much surplus.
    const MIN_TAB_BAR_CLEARANCE = 49;

    expect(typeof contentStyle.paddingBottom).toBe("number");
    expect(contentStyle.paddingBottom as number).toBeGreaterThanOrEqual(
      safeAreaBottom + MIN_TAB_BAR_CLEARANCE,
    );
  });
});
