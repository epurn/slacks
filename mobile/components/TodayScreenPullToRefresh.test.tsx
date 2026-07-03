import { act } from "react-test-renderer";
import { RefreshControl } from "react-native";

import { TodayScreen } from "./TodayScreen";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

import {
  INACTIVE,
  SESSION,
  cleanupTrees,
  event,
  hasA11yLabel,
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
    SymbolView: ({
      name,
      accessibilityLabel,
    }: {
      name: string;
      accessibilityLabel?: string;
    }) =>
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

jest.mock("@/api/logEvents", () => {
  const actual = jest.requireActual("@/api/logEvents");
  return {
    ...actual,
    listTodayLogEventEntries: jest.fn().mockResolvedValue([]),
  };
});

beforeEach(() => mockReduceMotion(false));

afterEach(cleanupTrees);

describe("TodayScreen pull-to-refresh (FTY-185)", () => {
  it("mounts a RefreshControl whose onRefresh re-runs the existing refetch", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "Oatmeal", status: "completed" }),
      ]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    // Initial load ran once; the timeline carries a RefreshControl trigger.
    expect(load).toHaveBeenCalledTimes(1);
    const control = tree.root.findByType(RefreshControl);
    expect(control.props.refreshing).toBe(false);

    // Pull-to-refresh fires the same refetch the header button used to.
    act(() => {
      control.props.onRefresh();
    });
    // While the load is in flight the platform spinner is shown.
    expect(tree.root.findByType(RefreshControl).props.refreshing).toBe(true);

    await act(async () => {});

    expect(load).toHaveBeenCalledTimes(2);
    // Spinner clears once the refetch settles.
    expect(tree.root.findByType(RefreshControl).props.refreshing).toBe(false);
  });

  it("removes the header manual-refresh button", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    // The old "Refresh" header action is gone; refresh is pull-to-refresh only.
    expect(hasA11yLabel(tree, "Refresh")).toBe(false);
    expect(hasA11yLabel(tree, "Refresh today")).toBe(true);
  });
});
