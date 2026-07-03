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

// The FTY-185 occlusion contract has three parts. `_layout.test.tsx` proves the
// first: the tab bar is a real, full-footprint expo-blur `.ultraThin` overlay
// (position:absolute, transparent background, BlurView `absoluteFill` at
// intensity 100). This suite proves the other two: (a) the Today timeline
// actually reserves clearance to scroll *beneath* that overlay, and (b) an
// app-drawn dimming fade (`TabBarScrim`) actually renders over the bottom of the
// screen so scrolled content visibly fades/dims into the surface — the story's
// "text is not legible through the tab labels" requirement — independent of the
// native blur, which the JS/Maestro harness cannot observe. The scrim is drawn
// by the app (plain Views with a surface-colour opacity ramp), so unlike the
// native blur its fade IS machine-assertable here.
describe("TodayScreen tab-bar occlusion (FTY-185)", () => {
  // Light-mode surface is the useTheme() default when no ThemeProvider wraps the
  // tree (as in these mounts); assert the fade paints in that colour.
  const SURFACE_LIGHT = "#F2F2F7";

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

  it("reserves bottom clearance so timeline content scrolls beneath the floating tab bar", async () => {
    const tree = mountToday();
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

  it("renders a dimming fade that ramps transparent→opaque surface so content is not legible through the tab labels", async () => {
    const tree = mountToday();
    await act(async () => {});

    // The fade overlay must exist, cover the bottom of the screen, and never
    // intercept touches/scroll.
    const scrim = tree.root.find((n) => n.props.testID === "tab-bar-scrim");
    expect(scrim.props.pointerEvents).toBe("none");
    const scrimStyle = StyleSheet.flatten(scrim.props.style) as {
      position?: string;
      bottom?: number;
      height?: number;
    };
    expect(scrimStyle.position).toBe("absolute");
    expect(scrimStyle.bottom).toBe(0);
    // The fade spans the reserved clearance zone (safe-area bottom + surplus),
    // so content dims across exactly the region it scrolls through under the bar.
    expect(scrimStyle.height as number).toBeGreaterThanOrEqual(34 + 49);

    // Each band's surface-colour opacity is the actual dimming applied to the
    // content behind it. Collect them top→bottom.
    const bands = tree.root.findAll(
      (n) =>
        // Host View instances only (`type` is the string tag) — a composite
        // `View` and its host child both carry the testID, so match one.
        typeof n.type === "string" &&
        typeof n.props.testID === "string" &&
        n.props.testID.startsWith("tab-bar-scrim-band-"),
    );
    expect(bands.length).toBeGreaterThan(1);

    const opacities = bands.map((band) => {
      const style = StyleSheet.flatten(band.props.style) as {
        backgroundColor?: string;
        opacity?: number;
      };
      // The fade dims *toward the surface* — every band paints the screen
      // colour, so content reads as fading into the background, not tinting.
      expect(style.backgroundColor).toBe(SURFACE_LIGHT);
      return style.opacity as number;
    });

    // A genuine fade: fully transparent at the top (content legible), fully
    // opaque surface at the bottom (content faded out under the tab labels),
    // increasing monotonically in between.
    expect(opacities[0]).toBe(0);
    expect(opacities[opacities.length - 1]).toBe(1);
    for (let i = 1; i < opacities.length; i += 1) {
      expect(opacities[i]).toBeGreaterThan(opacities[i - 1]);
    }
  });
});
