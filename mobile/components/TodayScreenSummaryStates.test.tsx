import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { LogEventApiError } from "@/api/logEvents";
import type { DailySummaryDTO } from "@/api/dailySummary";
import { mockReduceMotion } from "@/testUtils/reduceMotion";
import { ThemeProvider, darkPalette, lightPalette } from "@/theme";
import type { ColorSchemeOverride } from "@/theme";
import { TodayScreen } from "./TodayScreen";

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

const SESSION = {
  serverUrl: "https://api.example.test",
  token: "test-token",
  userId: "22222222-2222-2222-2222-222222222222",
};

const INACTIVE = () => false;

function summary(overrides: Partial<DailySummaryDTO> = {}): DailySummaryDTO {
  return {
    date: "2026-06-27",
    intake: { calories: 1234, protein_g: 70, carbs_g: 120, fat_g: 40 },
    has_intake: true,
    target: {
      calories: { effective: 2000, derived: 2000, source: "derived" },
      protein_g: { effective: 128, derived: 128, source: "derived" },
      carbs_g: { effective: 148, derived: 148, source: "derived" },
      fat_g: { effective: 64, derived: 64, source: "derived" },
    },
    exercise: { active_calories: 0 },
    ...overrides,
  };
}

function mount(
  element: React.ReactElement,
  themeOverride: ColorSchemeOverride = "light",
): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 390, height: 844 },
          insets: { top: 47, left: 0, right: 0, bottom: 34 },
        }}
      >
        <ThemeProvider override={themeOverride}>{element}</ThemeProvider>
      </SafeAreaProvider>,
    );
  });
  return tree;
}

function textContent(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

function a11yLabels(tree: ReactTestRenderer): string[] {
  return tree.root
    .findAll((n) => !!n.props.accessibilityLabel)
    .map((n) => n.props.accessibilityLabel as string);
}

function textNodeByContent(tree: ReactTestRenderer, content: string) {
  return tree.root.find(
    (n) => typeof n.props.children === "string" && n.props.children === content,
  );
}

function flattenedStyle(style: unknown): Record<string, unknown> {
  if (Array.isArray(style)) {
    return Object.assign({}, ...style.map(flattenedStyle));
  }
  return typeof style === "object" && style !== null
    ? (style as Record<string, unknown>)
    : {};
}

beforeEach(() => mockReduceMotion(false));

describe("TodayScreen summary states", () => {
  it("renders the populated hero with the exact consumed / target kcal format", async () => {
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={jest.fn().mockResolvedValue([])}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    expect(textContent(tree)).toContain("1,234 / 2,000 kcal · 62%");
    expect(a11yLabels(tree).some((label) => label.includes("1,234 of 2,000 kcal"))).toBe(
      true,
    );
  });

  it("keeps the hero shell visible when the summary fetch fails", async () => {
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={jest.fn().mockResolvedValue([])}
        getDailySummary={jest.fn().mockRejectedValue(new Error("network"))}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    expect(textContent(tree)).toContain("We couldn't load your summary");
    expect(textContent(tree)).toContain("Summary unavailable");
    expect(textContent(tree)).not.toContain("No target set");
    expect(textContent(tree)).toContain("Try again");
    expect(a11yLabels(tree).some((label) => label.includes("summary unavailable"))).toBe(
      true,
    );
  });

  it("renders the empty-day full-budget copy from has_intake false", async () => {
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={jest.fn().mockResolvedValue([])}
        getDailySummary={jest.fn().mockResolvedValue(
          summary({
            intake: { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 },
            has_intake: false,
          }),
        )}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    expect(textContent(tree)).toContain("0 / 2,000 kcal · 2,000 to go");
    expect(textContent(tree)).toContain("Log your first thing");
    expect(textContent(tree)).not.toContain("0%");
  });

  it("orders the screen hero → composer → macro tier (macro work is FTY-179)", async () => {
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={jest.fn().mockResolvedValue([])}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // findAll walks the rendered tree depth-first, so indices reflect
    // top-to-bottom screen order.
    const labels = a11yLabels(tree);
    const heroIndex = labels.findIndex((label) =>
      label.includes("1,234 of 2,000 kcal"),
    );
    const composerIndex = labels.indexOf("Log food or exercise");
    const proteinIndex = labels.findIndex((label) => label.startsWith("Protein:"));

    expect(heroIndex).toBeGreaterThanOrEqual(0);
    expect(composerIndex).toBeGreaterThan(heroIndex);
    expect(proteinIndex).toBeGreaterThan(composerIndex);
  });

  it("themes the timeline load-error text legibly in light and dark", async () => {
    const message = "Could not load your timeline.";
    const load = jest.fn().mockRejectedValue(new LogEventApiError(500, message));
    const getDailySummary = jest.fn().mockResolvedValue(summary());

    const lightTree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getDailySummary={getDailySummary}
        useActive={INACTIVE}
      />,
      "light",
    );
    await act(async () => {});

    const darkTree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getDailySummary={getDailySummary}
        useActive={INACTIVE}
      />,
      "dark",
    );
    await act(async () => {});

    expect(flattenedStyle(textNodeByContent(lightTree, message).props.style).color).toBe(
      lightPalette.textSecondary,
    );
    expect(flattenedStyle(textNodeByContent(darkTree, message).props.style).color).toBe(
      darkPalette.textSecondary,
    );
  });
});
