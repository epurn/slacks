import React from "react";
import { act, create } from "react-test-renderer";
import { useColorScheme } from "react-native";

import { ThemeProvider } from "@/theme";
import { type FoodSuggestionDTO } from "@/api/foodSuggestions";
import { QuickAddChips } from "./QuickAddChips";

const mockUseColorScheme = useColorScheme as jest.MockedFunction<
  typeof useColorScheme
>;

function mount(
  element: React.ReactElement,
  override: "light" | "dark" = "light",
) {
  let tree: ReturnType<typeof create> | null = null;
  act(() => {
    tree = create(
      React.createElement(ThemeProvider, { override }, element),
    );
  });
  return tree!;
}

function suggestion(overrides: Partial<FoodSuggestionDTO> = {}): FoodSuggestionDTO {
  return {
    label: "Greek yogurt",
    submit_phrase: "greek yogurt",
    saved_food_id: null,
    score: 1,
    ...overrides,
  };
}

function suggestionLabels(tree: ReturnType<typeof create>): string[] {
  return tree.root
    .findAll(
      (n) =>
        typeof n.type === "string" &&
        n.props.accessibilityRole === "button" &&
        typeof n.props.accessibilityLabel === "string" &&
        n.props.accessibilityLabel.startsWith("Suggestion: "),
    )
    .map((n) => n.props.accessibilityLabel as string);
}

describe("QuickAddChips", () => {
  beforeEach(() => mockUseColorScheme.mockReturnValue("light"));

  it("renders nothing (no empty shell) when there are no suggestions", () => {
    const tree = mount(<QuickAddChips suggestions={[]} onSelect={jest.fn()} />);
    expect(tree.root.findAll((n) => n.props.testID === "quick-add-chips")).toHaveLength(
      0,
    );
    expect(suggestionLabels(tree)).toHaveLength(0);
  });

  it("renders a chip per suggestion, in canonical server order", () => {
    const tree = mount(
      <QuickAddChips
        suggestions={[
          suggestion({ label: "Chicken burrito bowl", saved_food_id: "sf-1" }),
          suggestion({ label: "Greek yogurt" }),
          suggestion({ label: "Black coffee" }),
        ]}
        onSelect={jest.fn()}
      />,
    );
    // Server order is rendered verbatim — the client never re-ranks.
    expect(suggestionLabels(tree)).toEqual([
      "Suggestion: Chicken burrito bowl",
      "Suggestion: Greek yogurt",
      "Suggestion: Black coffee",
    ]);
  });

  it("gives each chip a VoiceOver 'Suggestion: <label>' label and the row is a skippable list", () => {
    const tree = mount(
      <QuickAddChips suggestions={[suggestion()]} onSelect={jest.fn()} />,
    );
    const row = tree.root.find((n) => n.props.testID === "quick-add-chips");
    expect(row.props.accessibilityRole).toBe("list");
    expect(row.props.accessibilityLabel).toBe("Quick-add suggestions");
    expect(suggestionLabels(tree)).toEqual(["Suggestion: Greek yogurt"]);
  });

  it("passes the tapped suggestion to onSelect", () => {
    const onSelect = jest.fn();
    const yogurt = suggestion();
    const tree = mount(
      <QuickAddChips suggestions={[yogurt]} onSelect={onSelect} />,
    );
    act(() => {
      tree.root
        .find((n) => n.props.accessibilityLabel === "Suggestion: Greek yogurt")
        .props.onPress();
    });
    expect(onSelect).toHaveBeenCalledWith(yogurt);
  });
});
