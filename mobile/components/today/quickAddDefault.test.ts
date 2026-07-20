import { type FoodSuggestionDTO } from "@/api/foodSuggestions";

import { matchQuickAddDefault } from "./quickAddDefault";

function suggestion(overrides: Partial<FoodSuggestionDTO> = {}): FoodSuggestionDTO {
  return {
    label: "Black coffee",
    submit_phrase: "black coffee",
    saved_food_id: null,
    score: 1,
    ...overrides,
  };
}

describe("matchQuickAddDefault", () => {
  const priorFoods = [
    suggestion({ label: "Black coffee", submit_phrase: "black coffee" }),
    suggestion({ label: "Greek yogurt", submit_phrase: "greek yogurt" }),
  ];

  it("offers the prior food when the typed name matches (name-normalized)", () => {
    const match = matchQuickAddDefault("  BLACK   coffee ", priorFoods);
    expect(match?.submit_phrase).toBe("black coffee");
  });

  it("offers the prior food on a normalized prefix so it surfaces while typing", () => {
    const match = matchQuickAddDefault("black cof", priorFoods);
    expect(match?.label).toBe("Black coffee");
  });

  it("prefers an exact normalized match over a prefix match", () => {
    const pool = [
      suggestion({ label: "Coffee cake", submit_phrase: "coffee cake" }),
      suggestion({ label: "Coffee", submit_phrase: "coffee" }),
    ];
    expect(matchQuickAddDefault("coffee", pool)?.submit_phrase).toBe("coffee");
  });

  it("returns null when no prior food matches — quick-add unchanged (no regression)", () => {
    expect(matchQuickAddDefault("pad thai", priorFoods)).toBeNull();
  });

  it("returns null for an empty or whitespace-only query", () => {
    expect(matchQuickAddDefault("", priorFoods)).toBeNull();
    expect(matchQuickAddDefault("   ", priorFoods)).toBeNull();
  });

  it("ignores saved foods — those are served by the saved-food typeahead", () => {
    const savedOnly = [
      suggestion({ label: "Black coffee", saved_food_id: "sf-1" }),
    ];
    expect(matchQuickAddDefault("black coffee", savedOnly)).toBeNull();
  });

  it("draws only from the provided owner-scoped pool", () => {
    // An empty pool (a user with no matching history) never surfaces a default,
    // so nothing from another user's history could leak in.
    expect(matchQuickAddDefault("black coffee", [])).toBeNull();
  });
});
