import { Animated } from "react-native";
import { act, create as render, type ReactTestRenderer } from "react-test-renderer";

import { ItemTimelineRow } from "./ItemTimelineRow";
import type { DerivedFoodItemDTO, DerivedExerciseItemDTO, ItemSourceDTO } from "@/api/derivedItems";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

// expo-symbols is a native module — replace SymbolView with a View stub that
// exposes the symbol name via testID (same pattern as AppIcon.test.tsx); the
// ProvenanceIcon inside the row renders through it.
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
      tintColor?: string;
      size?: number;
      accessibilityLabel?: string;
    }) =>
      React.createElement(View, {
        testID: `sf-symbol-${String(name)}`,
        accessibilityLabel,
      }),
  };
});

function usdaSource(): ItemSourceDTO {
  return { source_type: "trusted_nutrition_database", label: "USDA", ref: "usda_fdc:168880" };
}

function foodItem(overrides: Partial<DerivedFoodItemDTO> = {}): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: "item-1",
    user_id: "user-1",
    log_event_id: "event-1",
    name: "Greek yogurt",
    quantity_text: "1 cup",
    unit: "cup",
    amount: 1,
    status: "resolved",
    grams: 245,
    calories: 150,
    protein_g: 20,
    carbs_g: 8,
    fat_g: 4,
    calories_estimated: 150,
    protein_g_estimated: 20,
    carbs_g_estimated: 8,
    fat_g_estimated: 4,
    source: usdaSource(),
    is_edited: false,
    created_at: "2026-06-27T08:00:00Z",
    updated_at: "2026-06-27T08:00:00Z",
    ...overrides,
  };
}

function exerciseItem(
  overrides: Partial<DerivedExerciseItemDTO> = {},
): DerivedExerciseItemDTO {
  return {
    item_type: "exercise",
    id: "ex-1",
    user_id: "user-1",
    log_event_id: "event-2",
    name: "Running",
    quantity_text: "30 min",
    unit: "min",
    amount: 30,
    status: "resolved",
    active_calories: 280,
    active_calories_estimated: 280,
    source: null,
    is_edited: false,
    created_at: "2026-06-27T07:30:00Z",
    updated_at: "2026-06-27T07:30:00Z",
    ...overrides,
  };
}

function firstA11yLabel(tree: ReactTestRenderer): string {
  return tree.root.find((n) => !!n.props.accessibilityLabel).props
    .accessibilityLabel as string;
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

// A fake Animated driver that finishes synchronously, so the resolve-fade
// animation never keeps a loop ticking after teardown. Spies still record calls.
const FAKE_ANIM = { start: (cb?: (r: { finished: boolean }) => void) => cb?.({ finished: true }), stop: () => {} };

beforeEach(() => {
  // Reduce Motion off by default (synchronous stub) so the resolve fade takes
  // its spring path and no async setState leaks past `act`.
  mockReduceMotion(false);
  jest.spyOn(Animated, "spring").mockReturnValue(FAKE_ANIM as never);
  jest.spyOn(Animated, "timing").mockReturnValue(FAKE_ANIM as never);
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe("ItemTimelineRow — food item", () => {
  it("shows name, kcal, and always-on source icon", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<ItemTimelineRow item={foodItem()} />);
    });

    const text = allText(tree!);
    expect(text).toContain("Greek yogurt");
    expect(text).toContain("150 kcal");

    const labels = allA11yLabels(tree!);
    // Source icon a11y label is present
    expect(labels.some((l) => l.includes("USDA"))).toBe(true);
  });

  it("row a11y label includes name and kcal", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<ItemTimelineRow item={foodItem({ name: "Oatmeal", calories: 205 })} />);
    });

    const label = firstA11yLabel(tree!);
    expect(label).toContain("Oatmeal");
    expect(label).toContain("205 kcal");
  });

  it("is_edited item shows ✎ source icon with 'Edited by you' label", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<ItemTimelineRow item={foodItem({ is_edited: true })} />);
    });

    const labels = allA11yLabels(tree!);
    expect(labels.some((l) => l === "Edited by you")).toBe(true);
  });

  it("tapping calls onPress", () => {
    const onPress = jest.fn();
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<ItemTimelineRow item={foodItem()} onPress={onPress} />);
    });

    act(() => {
      tree!.root
        .find((n) => n.props.accessibilityRole === "button")
        .props.onPress();
    });

    expect(onPress).toHaveBeenCalledTimes(1);
  });
});

describe("ItemTimelineRow — exercise item", () => {
  it("shows exercise name and active_calories", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<ItemTimelineRow item={exerciseItem()} />);
    });

    const text = allText(tree!);
    expect(text).toContain("Running");
    expect(text).toContain("280 kcal");
  });

  it("row a11y label mentions burned for exercise", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<ItemTimelineRow item={exerciseItem({ active_calories: 200 })} />);
    });

    const label = firstA11yLabel(tree!);
    expect(label).toContain("Running");
    expect(label).toContain("200 kcal burned");
  });
});

describe("ItemTimelineRow — needs_clarification", () => {
  it("renders muted with 'needs a detail' tag", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <ItemTimelineRow item={foodItem()} needsClarification />,
      );
    });

    const text = allText(tree!);
    expect(text).toContain("needs a detail");
  });

  it("shows '—' for kcal (visibly uncounted)", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<ItemTimelineRow item={foodItem()} needsClarification />);
    });

    const text = allText(tree!);
    expect(text).toContain("—");
    // Should NOT show the numeric kcal value
    expect(text).not.toContain("150 kcal");
  });

  it("row a11y label mentions 'needs a detail' and uncounted", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<ItemTimelineRow item={foodItem()} needsClarification />);
    });

    const label = firstA11yLabel(tree!);
    expect(label).toContain("needs a detail");
    expect(label).toContain("uncounted");
  });

  it("tap calls onPress (clarify hook)", () => {
    const onPress = jest.fn();
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(
        <ItemTimelineRow item={foodItem()} needsClarification onPress={onPress} />,
      );
    });

    act(() => {
      tree!.root
        .find((n) => n.props.accessibilityRole === "button")
        .props.onPress();
    });

    expect(onPress).toHaveBeenCalledTimes(1);
  });
});

/** Resolve the style object for a node, collapsing a Pressable style function. */
function rowGeometry(node: { props: { style?: unknown } }): Record<string, unknown> {
  const raw =
    typeof node.props.style === "function"
      ? (node.props.style as (s: { pressed: boolean }) => unknown)({ pressed: false })
      : node.props.style;
  return Object.assign(
    {},
    ...([] as unknown[]).concat(raw).filter(Boolean) as Record<string, unknown>[],
  );
}

describe("ItemTimelineRow — loading (FTY-180)", () => {
  beforeEach(() => {
    mockReduceMotion(false);
    // `mockReduceMotion` resolves the Reduce Motion check synchronously, so
    // both the Skeleton's shimmer-loop effect and the row's own resolve-fade
    // effect run inside the same `act()` call as render. Stub `Animated.loop`
    // and `Animated.timing` so no real requestAnimationFrame-driven animation
    // is left running past the test (it would otherwise keep the Jest process
    // alive) — their own behaviour is Skeleton's / the resolve-fade tests'
    // concern, covered elsewhere.
    jest
      .spyOn(Animated, "loop")
      .mockReturnValue({ start: jest.fn(), stop: jest.fn() } as never);
    jest
      .spyOn(Animated, "timing")
      .mockReturnValue({ start: jest.fn(), stop: jest.fn() } as never);
  });
  afterEach(() => jest.restoreAllMocks());

  it("renders a Skeleton shimmer, never literal 'Waiting'/'Estimating' text", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<ItemTimelineRow loading accessibilityLabel="Waiting to estimate" />);
    });

    const text = allText(tree!);
    expect(text).not.toContain("Waiting");
    expect(text).not.toContain("Estimating");
  });

  it("conveys the in-progress status to VoiceOver via accessibilityRole + accessibilityLabel", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<ItemTimelineRow loading accessibilityLabel="Estimating" />);
    });

    const node = tree!.root.find(
      (n) => n.props.accessibilityRole === "progressbar",
    );
    expect(node.props.accessibilityLabel).toBe("Estimating");
  });

  it("hides each shimmer placeholder from the accessibility tree so VoiceOver reads one loading state, not three", () => {
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<ItemTimelineRow loading accessibilityLabel="Estimating" />);
    });

    // Every Skeleton placeholder is marked hidden-with-descendants so only the
    // row's own "Estimating" label reaches VoiceOver, not each block's default
    // "Loading" label three times over.
    const hiddenSkeletons = tree!.root.findAll(
      (n) =>
        n.props.accessibilityElementsHidden === true &&
        n.props.importantForAccessibility === "no-hide-descendants",
    );
    expect(hiddenSkeletons.length).toBeGreaterThanOrEqual(3);
  });

  it("uses the same row geometry (height, insets) as the resolved row — zero layout shift on resolve", () => {
    let loadingTree: ReactTestRenderer;
    let resolvedTree: ReactTestRenderer;
    act(() => {
      loadingTree = render(
        <ItemTimelineRow loading accessibilityLabel="Estimating" />,
      );
    });
    act(() => {
      resolvedTree = render(<ItemTimelineRow item={foodItem()} />);
    });

    const loadingRow = loadingTree!.root.find(
      (n) => n.props.accessibilityRole === "progressbar",
    );
    const resolvedRow = resolvedTree!.root.find(
      (n) => n.props.accessibilityRole === "button",
    );

    const loadingGeometry = rowGeometry(loadingRow);
    const resolvedGeometry = rowGeometry(resolvedRow);

    expect(loadingGeometry.minHeight).toBe(resolvedGeometry.minHeight);
    expect(loadingGeometry.paddingVertical).toBe(resolvedGeometry.paddingVertical);
    expect(loadingGeometry.paddingHorizontal).toBe(resolvedGeometry.paddingHorizontal);
    expect(loadingGeometry.gap).toBe(resolvedGeometry.gap);
  });

  it("does not animate the shimmer under Reduce Motion (degrades to a static placeholder)", async () => {
    mockReduceMotion(true);
    const loopSpy = jest
      .spyOn(Animated, "loop")
      .mockReturnValue({ start: jest.fn(), stop: jest.fn() } as never);

    act(() => {
      render(<ItemTimelineRow loading accessibilityLabel="Estimating" />);
    });
    await act(async () => {});

    expect(loopSpy).not.toHaveBeenCalled();
  });
});

describe("ItemTimelineRow — beat 1: resolve fade (FTY-180/181)", () => {
  afterEach(() => jest.restoreAllMocks());

  it("resolves in place: one instance goes loading→resolved and eases the value in on the transition, not during loading (animateResolve)", () => {
    mockReduceMotion(false);
    // The Skeleton shimmer drives Animated.loop/timing; the resolve fade is a
    // spring (Reduce Motion off), so assert on spring to isolate the beat.
    jest
      .spyOn(Animated, "loop")
      .mockReturnValue({ start: jest.fn(), stop: jest.fn() } as never);

    // Mount as the loading skeleton, then update the SAME tree to resolved with
    // animateResolve. The timeline keys the pending row and the first resolved
    // row by the same event id, so React reuses this one instance — exactly what
    // drives the in-place fade.
    let tree: ReactTestRenderer;
    act(() => {
      tree = render(<ItemTimelineRow loading accessibilityLabel="Estimating" />);
    });

    // While loading, the resolve fade has not run — the shimmer owns the visuals.
    expect(Animated.spring).not.toHaveBeenCalled();

    act(() => {
      tree!.update(<ItemTimelineRow item={foodItem()} animateResolve />);
    });

    // The value row is now present (no longer a progressbar) and the fade played
    // on the transition — the resolved value eased in over the skeleton footprint.
    expect(
      tree!.root.findAll((n) => n.props.accessibilityRole === "progressbar"),
    ).toHaveLength(0);
    expect(allA11yLabels(tree!)).toContain("Greek yogurt, 150 kcal");
    expect(Animated.spring).toHaveBeenCalled();
  });

  it("eases the value in with a spring when the row resolves (animateResolve)", () => {
    act(() => {
      render(<ItemTimelineRow item={foodItem()} animateResolve />);
    });
    expect(Animated.spring).toHaveBeenCalled();
  });

  it("does not animate a row that is not a fresh resolve (default)", () => {
    act(() => {
      render(<ItemTimelineRow item={foodItem()} />);
    });
    expect(Animated.spring).not.toHaveBeenCalled();
    expect(Animated.timing).not.toHaveBeenCalled();
  });

  it("degrades to a simple fade (no spring) under Reduce Motion", () => {
    mockReduceMotion(true);
    act(() => {
      render(<ItemTimelineRow item={foodItem()} animateResolve />);
    });
    expect(Animated.spring).not.toHaveBeenCalled();
    expect(Animated.timing).toHaveBeenCalled();
  });
});
