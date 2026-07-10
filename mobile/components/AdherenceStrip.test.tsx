import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { ScrollView, View } from "react-native";

import { AdherenceStrip } from "@/components/AdherenceStrip";
import type { AdherenceDay } from "@/state/trends";
import { ThemeProvider, darkPalette, lightPalette } from "@/theme";

const mockScrollToEnd = jest.fn();

jest.mock("react-native", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require("react");
  const actual = jest.requireActual("react-native");

  const MockScrollView = React.forwardRef(
    (
      { children, ...props }: { children?: React.ReactNode },
      ref: React.ForwardedRef<{ scrollToEnd: (options: { animated: boolean }) => void }>,
    ) => {
      React.useImperativeHandle(ref, () => ({
        scrollToEnd: mockScrollToEnd,
      }));
      return React.createElement(actual.ScrollView, props, children);
    },
  );
  MockScrollView.displayName = "ScrollView";

  return new Proxy(actual, {
    get(target, prop, receiver) {
      if (prop === "ScrollView") {
        return MockScrollView;
      }
      return Reflect.get(target, prop, receiver);
    },
  });
});

function day(date: string, state: AdherenceDay["state"]): AdherenceDay {
  return {
    date,
    state,
    intakeCalories:
      state === "on-target" ? 1980 : state === "off-target" ? 1500 : null,
    targetCalories:
      state === "on-target" || state === "off-target" ? 2000 : null,
  };
}

function longRecentLoggedWindow(): AdherenceDay[] {
  return [
    day("2026-06-01", "no-data"),
    day("2026-06-02", "no-data"),
    day("2026-06-03", "no-data"),
    day("2026-06-04", "no-data"),
    day("2026-06-05", "no-data"),
    day("2026-06-06", "no-data"),
    day("2026-06-07", "no-data"),
    day("2026-06-08", "no-data"),
    day("2026-06-09", "no-data"),
    day("2026-06-10", "no-data"),
    day("2026-06-11", "no-data"),
    day("2026-06-12", "no-data"),
    day("2026-06-13", "no-data"),
    day("2026-06-14", "no-data"),
    day("2026-06-15", "no-data"),
    day("2026-06-16", "no-data"),
    day("2026-06-17", "no-data"),
    day("2026-06-18", "no-data"),
    day("2026-06-19", "on-target"),
    day("2026-06-20", "off-target"),
    day("2026-06-21", "on-target"),
    day("2026-06-22", "on-target"),
    day("2026-06-23", "on-target"),
    day("2026-06-24", "off-target"),
    day("2026-06-25", "on-target"),
    day("2026-06-26", "on-target"),
    day("2026-06-27", "on-target"),
    day("2026-06-28", "on-target"),
    day("2026-06-29", "off-target"),
    day("2026-06-30", "on-target"),
  ];
}

function shortWindow(): AdherenceDay[] {
  return [
    day("2026-06-27", "no-data"),
    day("2026-06-28", "no-target"),
    day("2026-06-29", "off-target"),
    day("2026-06-30", "on-target"),
  ];
}

function mount(
  days: readonly AdherenceDay[],
  {
    onDayPress,
    theme = "light",
  }: {
    onDayPress?: (date: string) => void;
    theme?: "light" | "dark";
  } = {},
): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <ThemeProvider override={theme}>
        <AdherenceStrip
          days={days}
          today="2026-06-30"
          onDayPress={onDayPress}
        />
      </ThemeProvider>,
    );
  });
  return tree;
}

function cellNodes(tree: ReactTestRenderer) {
  const seen = new Set<string>();
  return tree.root.findAll(
    (n) =>
      typeof n.props.testID === "string" &&
      (n.props.testID as string).startsWith("adherence-cell-"),
  ).filter((n) => {
    const testID = n.props.testID as string;
    if (seen.has(testID)) {
      return false;
    }
    seen.add(testID);
    return true;
  });
}

function flattenedStyle(node: { props: { style?: unknown } }): Record<string, unknown> {
  const styles = Array.isArray(node.props.style) ? node.props.style : [node.props.style];
  return Object.assign({}, ...styles.filter(Boolean));
}

function fillStyle(tree: ReactTestRenderer, date: string): Record<string, unknown> {
  const cell = tree.root.find((n) => n.props.testID === `adherence-cell-${date}`);
  const fill = cell.findAllByType(View).find((node) => flattenedStyle(node).width === 10)!;
  return flattenedStyle(fill);
}

describe("AdherenceStrip", () => {
  beforeEach(() => {
    mockScrollToEnd.mockClear();
  });

  it("lands a long recent-logged window on its newest cells without changing chronological cell semantics", () => {
    const onDayPress = jest.fn();
    const tree = mount(longRecentLoggedWindow(), { onDayPress });

    const scrollView = tree.root.findByType(ScrollView);
    act(() => {
      scrollView.props.onContentSizeChange(1320, 44);
    });

    expect(mockScrollToEnd).toHaveBeenCalledWith({ animated: false });
    expect(mockScrollToEnd.mock.calls.length).toBeGreaterThanOrEqual(2);

    const cells = cellNodes(tree);
    expect(cells.map((n) => n.props.testID)).toEqual(
      longRecentLoggedWindow().map((d) => `adherence-cell-${d.date}`),
    );
    expect(cells[cells.length - 1]?.props.testID).toBe("adherence-cell-2026-06-30");
    expect(cells[cells.length - 1]?.props.accessibilityLabel).toBe("Today: on target");
    expect(cells[cells.length - 2]?.props.accessibilityLabel).toBe("Yesterday: off target");
    expect(cells[0]?.props.accessibilityLabel).toBe("June 1: no data");

    const tapTarget = flattenedStyle(cells[0]!);
    expect(tapTarget.minWidth).toBeGreaterThanOrEqual(44);
    expect(tapTarget.minHeight).toBeGreaterThanOrEqual(44);

    expect(fillStyle(tree, "2026-06-19")).toEqual(
      expect.objectContaining({ backgroundColor: lightPalette.accent }),
    );
    expect(fillStyle(tree, "2026-06-20")).toEqual(
      expect.objectContaining({
        backgroundColor: lightPalette.coral,
        borderWidth: 2,
        borderColor: lightPalette.surface,
      }),
    );
    expect(fillStyle(tree, "2026-06-18")).toEqual(
      expect.objectContaining({ backgroundColor: lightPalette.separator }),
    );

    act(() => {
      cells[cells.length - 1]?.props.onPress();
    });
    expect(onDayPress).toHaveBeenCalledWith("2026-06-30");
  });

  it("keeps short windows ordered and scrolls to the recent end without restyling states", () => {
    const tree = mount(shortWindow(), { theme: "dark" });

    expect(mockScrollToEnd).toHaveBeenCalledWith({ animated: false });
    expect(cellNodes(tree).map((n) => n.props.testID)).toEqual([
      "adherence-cell-2026-06-27",
      "adherence-cell-2026-06-28",
      "adherence-cell-2026-06-29",
      "adherence-cell-2026-06-30",
    ]);
    expect(fillStyle(tree, "2026-06-28")).toEqual(
      expect.objectContaining({
        backgroundColor: "transparent",
        borderWidth: 1,
        borderColor: darkPalette.textMuted,
        opacity: 0.6,
      }),
    );
    expect(fillStyle(tree, "2026-06-29")).toEqual(
      expect.objectContaining({
        backgroundColor: darkPalette.coral,
        borderWidth: 2,
        borderColor: darkPalette.surface,
      }),
    );
  });

  it("lands on the newest end again when the rendered range changes", () => {
    const tree = mount(shortWindow());
    mockScrollToEnd.mockClear();

    act(() => {
      tree.update(
        <ThemeProvider override="light">
          <AdherenceStrip
            days={longRecentLoggedWindow()}
            today="2026-06-30"
          />
        </ThemeProvider>,
      );
    });

    expect(mockScrollToEnd).toHaveBeenCalledWith({ animated: false });
    const cells = cellNodes(tree);
    expect(cells[cells.length - 1]?.props.testID).toBe("adherence-cell-2026-06-30");
  });
});
