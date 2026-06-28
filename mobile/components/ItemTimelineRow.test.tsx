import { act, create as render, type ReactTestRenderer } from "react-test-renderer";

import { ItemTimelineRow } from "./ItemTimelineRow";
import type { DerivedFoodItemDTO, DerivedExerciseItemDTO, ItemSourceDTO } from "@/api/derivedItems";

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
