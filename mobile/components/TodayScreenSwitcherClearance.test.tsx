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

// FTY-257: the floating switcher (FTY-242) replaced the full-width tab bar and
// its dimming scrim. This suite proves Today's scroll content reserves bottom
// clearance derived from the shared `floatingSwitcherClearance` inset — not a
// re-hardcoded pill height — so the last row scrolls clear of the pill and the
// home indicator.
describe("TodayScreen switcher clearance (FTY-257)", () => {
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

  it("reserves bottom clearance at least equal to the shared switcher inset", async () => {
    const tree = mountToday();
    await act(async () => {});

    const scroll = tree.root.find((n) => n.props.testID === "today-screen");
    const contentStyle = StyleSheet.flatten(
      scroll.props.contentContainerStyle,
    ) as { paddingBottom?: number };

    // The safe-area bottom inset seeded by the test SafeAreaProvider metrics
    // (see `mount` in todayTestUtils).
    const safeAreaBottom = 34;

    expect(typeof contentStyle.paddingBottom).toBe("number");
    expect(contentStyle.paddingBottom).toBe(
      floatingSwitcherClearance(safeAreaBottom),
    );
  });
});
