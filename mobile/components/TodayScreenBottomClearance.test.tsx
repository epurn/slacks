import { StyleSheet } from "react-native";
import { act } from "react-test-renderer";

import { TodayScreen } from "./TodayScreen";
import { floatingSwitcherClearance } from "@/components/ui";
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

// FTY-242: the full-width bottom tab bar (and its FTY-185 dimming scrim) are
// retired in favour of the bottom-left floating switcher. Today no longer draws a
// full-width fade; instead it reserves bottom clearance sourced from the
// switcher's own footprint so its last timeline row scrolls clear of the pill and
// the home indicator. These tests prove that reservation and the scrim's removal.
describe("TodayScreen bottom clearance (FTY-242 floating switcher)", () => {
  function mountToday() {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "Oatmeal", status: "completed" }),
      ]);
    return mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
  }

  it("reserves clearance for the floating switcher + home indicator", async () => {
    const tree = mountToday();
    await act(async () => {});

    const scroll = tree.root.find((n) => n.props.testID === "today-screen");
    const contentStyle = StyleSheet.flatten(
      scroll.props.contentContainerStyle,
    ) as { paddingBottom?: number };

    // The safe-area bottom inset seeded by the test SafeAreaProvider metrics
    // (see `mount` in todayTestUtils).
    const safeAreaBottom = 34;
    // The reserved clearance is the switcher's single source of truth — the
    // content must reserve exactly that so the last row clears the pill.
    expect(contentStyle.paddingBottom).toBe(
      floatingSwitcherClearance(safeAreaBottom),
    );
  });

  it("no longer renders a tab-bar-scrim artifact", async () => {
    const tree = mountToday();
    await act(async () => {});

    const scrims = tree.root.findAll(
      (n) =>
        typeof n.props.testID === "string" &&
        n.props.testID.startsWith("tab-bar-scrim"),
    );
    expect(scrims).toHaveLength(0);
  });
});
