/**
 * Focused tests for the extracted TargetRow (FTY-203).
 *
 * TargetRow now owns the provenance display + reset-affordance logic that used
 * to live inline in SettingsScreen, so it is proven here in isolation: a derived
 * value reads "└ from your goal + metrics" with no Reset; a user override reads
 * "✎ set by you" and exposes a Reset that fires with the derived value in its
 * VoiceOver label.
 */

import React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { ThemeProvider, useTheme } from "@/theme";
import type { TargetReadModel } from "@/api/dailySummary";

import { TargetRow } from "./TargetRow";

/** Renders TargetRow with a real resolved palette from the ThemeProvider. */
function Harness(props: {
  component: TargetReadModel["calories"];
  onOverride: () => void;
  onReset: () => void;
}) {
  const { colors } = useTheme();
  return (
    <TargetRow
      label="Calories"
      unit="kcal"
      component={props.component}
      onOverride={props.onOverride}
      onReset={props.onReset}
      colors={colors}
      testID="calorie-target-row"
    />
  );
}

function renderRow(props: {
  component: TargetReadModel["calories"];
  onOverride?: () => void;
  onReset?: () => void;
}): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <ThemeProvider override="light">
        <Harness
          component={props.component}
          onOverride={props.onOverride ?? (() => {})}
          onReset={props.onReset ?? (() => {})}
        />
      </ThemeProvider>,
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

const DERIVED = { effective: 1800, derived: 1800, source: "derived" } as const;
const USER = { effective: 2000, derived: 1800, source: "user" } as const;

describe("TargetRow", () => {
  it("shows the derived provenance and no Reset for a derived value", () => {
    const tree = renderRow({ component: DERIVED });
    expect(textContent(tree)).toContain("└ from your goal + metrics");
    expect(textContent(tree)).toContain("1800 kcal");
    const resets = tree.root.findAll(
      (n) =>
        typeof n.props.accessibilityLabel === "string" &&
        (n.props.accessibilityLabel as string).startsWith("Reset Calories"),
    );
    expect(resets).toHaveLength(0);
  });

  it("shows the user provenance and a Reset labelled with the derived value", () => {
    const onReset = jest.fn();
    const tree = renderRow({ component: USER, onReset });
    expect(textContent(tree)).toContain("✎ set by you");

    const reset = tree.root.find(
      (n) =>
        n.props.accessibilityLabel ===
          "Reset Calories to derived value of 1800 kcal" &&
        typeof n.props.onPress === "function",
    );
    act(() => {
      reset.props.onPress();
    });
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it("opens the override editor when the row body is pressed", () => {
    const onOverride = jest.fn();
    const tree = renderRow({ component: DERIVED, onOverride });
    const rowBody = tree.root.find(
      (n) =>
        n.props.accessibilityLabel ===
          "Calories: 1800 kcal. Derived from your goal and metrics" &&
        typeof n.props.onPress === "function",
    );
    act(() => {
      rowBody.props.onPress();
    });
    expect(onOverride).toHaveBeenCalledTimes(1);
  });
});
