import { act, create as render, type ReactTestRenderer } from "react-test-renderer";

import { MacroTier } from "./MacroTier";
import type { TargetReadModel } from "@/api/dailySummary";

// expo-symbols is a native module — replace SymbolView with a View stub that
// exposes the requested SF Symbol name via testID so tests can assert the burn
// glyph comes from the icon system (not an emoji).
jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require("react");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require("react-native");
  return {
    SymbolView: ({
      name,
      accessibilityLabel,
    }: {
      name: string;
      accessibilityLabel?: string;
    }) =>
      React.createElement(View, {
        testID: `sf-symbol-${String(name)}`,
        accessibilityLabel,
      }),
  };
});

/** A derived-only target read-model with the given per-macro effective grams. */
function targetModel(p: number, c: number, f: number): TargetReadModel {
  return {
    calories: { effective: 2000, derived: 2000, source: "derived" },
    protein_g: { effective: p, derived: p, source: "derived" },
    carbs_g: { effective: c, derived: c, source: "derived" },
    fat_g: { effective: f, derived: f, source: "derived" },
  };
}

function allA11yLabels(tree: ReactTestRenderer): string[] {
  return tree.root
    .findAll((n) => !!n.props.accessibilityLabel)
    .map((n) => n.props.accessibilityLabel as string);
}

function allText(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

function symbolNames(tree: ReactTestRenderer): string[] {
  return tree.root
    .findAll(
      (n) =>
        typeof n.props.testID === "string" &&
        n.props.testID.startsWith("sf-symbol-"),
    )
    .map((n) => (n.props.testID as string).replace("sf-symbol-", ""));
}

describe("MacroTier — macro chips vs. targets", () => {
  it("renders compact chips reading consumed/target from target.*.effective", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <MacroTier
          protein_g={80}
          carbs_g={150}
          fat_g={40}
          target={targetModel(155, 200, 60)}
          active_calories={0}
        />,
      );
    });

    const text = allText(tree!);
    expect(text).toContain("80/155g");
    expect(text).toContain("150/200g");
    expect(text).toContain("40/60g");

    const labels = allA11yLabels(tree!);
    expect(labels).toContain("Protein 80 of 155 grams");
    expect(labels).toContain("Carbs 150 of 200 grams");
    expect(labels).toContain("Fat 40 of 60 grams");
  });

  it("rounds fractional consumed grams; targets are whole", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <MacroTier
          protein_g={80.7}
          carbs_g={149.2}
          fat_g={40.5}
          target={targetModel(155, 200, 60)}
          active_calories={0}
        />,
      );
    });

    const labels = allA11yLabels(tree!);
    expect(labels).toContain("Protein 81 of 155 grams");
    expect(labels).toContain("Carbs 149 of 200 grams");
    expect(labels).toContain("Fat 41 of 60 grams");
  });

  it("falls back to consumed-only chips (no denominator) when target is null", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <MacroTier
          protein_g={80}
          carbs_g={150}
          fat_g={40}
          target={null}
          active_calories={0}
        />,
      );
    });

    const text = allText(tree!);
    expect(text).toContain("80g");
    expect(text).toContain("150g");
    expect(text).toContain("40g");
    // No fabricated denominator.
    expect(text).not.toContain("/");

    const labels = allA11yLabels(tree!);
    expect(labels).toContain("Protein 80 grams");
    expect(labels).toContain("Carbs 150 grams");
    expect(labels).toContain("Fat 40 grams");
    expect(labels.some((l) => l.includes(" of "))).toBe(false);
  });
});

describe("MacroTier — distinct burn line", () => {
  it("renders a distinct burn line from active_calories, using the icon system (no emoji)", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <MacroTier
          protein_g={80}
          carbs_g={150}
          fat_g={40}
          target={targetModel(155, 200, 60)}
          active_calories={300}
        />,
      );
    });

    const labels = allA11yLabels(tree!);
    expect(labels).toContain("Burned: 300 kcal");

    const text = allText(tree!);
    expect(text).toContain("300 kcal burned");
    // No emoji as UI chrome — the flame is an SF Symbol, not a literal 🔥.
    expect(text).not.toContain("🔥");
    expect(symbolNames(tree!)).toContain("flame.fill");
  });

  it("hides the burn line calmly when active_calories is 0", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <MacroTier
          protein_g={80}
          carbs_g={150}
          fat_g={40}
          target={targetModel(155, 200, 60)}
          active_calories={0}
        />,
      );
    });

    const labels = allA11yLabels(tree!);
    expect(labels.some((l) => l.includes("Burned"))).toBe(false);
    expect(allText(tree!)).not.toContain("burned");
    expect(symbolNames(tree!)).not.toContain("flame.fill");
  });

  it("keeps burn separate from food math: not a fourth macro chip, never netted", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <MacroTier
          protein_g={80}
          carbs_g={150}
          fat_g={40}
          target={targetModel(155, 200, 60)}
          active_calories={210}
        />,
      );
    });

    const labels = allA11yLabels(tree!);
    expect(labels.some((l) => l.startsWith("Protein"))).toBe(true);
    expect(labels.some((l) => l.startsWith("Carbs"))).toBe(true);
    expect(labels.some((l) => l.startsWith("Fat"))).toBe(true);
    // Exercise is not exposed as a macro chip.
    const exerciseAsChip = labels.filter(
      (l) =>
        l.startsWith("Exercise") ||
        l.startsWith("Burn ") ||
        l.startsWith("Calories burned"),
    );
    expect(exerciseAsChip).toHaveLength(0);

    // The burn figure is shown verbatim (210), never subtracted into the macros.
    const text = allText(tree!);
    expect(text).toContain("210 kcal burned");
    expect(text).toContain("80/155g");
  });
});
