/**
 * FTY-204: Focused tests for the correction sheet's extracted error/format
 * helpers. The behaviour is also exercised through CorrectionSheet.test.tsx; this
 * pins the pure functions directly now that they carry standalone responsibility.
 */

import { CorrectionsApiError } from "@/api/corrections";
import {
  DerivedItemApiError,
  type DerivedExerciseItemDTO,
  type DerivedFoodItemDTO,
  type ItemSourceDTO,
} from "@/api/derivedItems";

import {
  formatAmount,
  isExactUpgradeEligible,
  messageForError,
  SEARCH_DEBOUNCE_MS,
} from "./helpers";

describe("messageForError", () => {
  it("passes through a CorrectionsApiError message verbatim", () => {
    const err = new CorrectionsApiError(422, "That correction couldn't be applied.");
    expect(messageForError(err, "apply that match")).toBe(
      "That correction couldn't be applied.",
    );
  });

  it("passes through a DerivedItemApiError message verbatim", () => {
    const err = new DerivedItemApiError(422, "That value couldn't be saved.");
    expect(messageForError(err, "save that override")).toBe(
      "That value couldn't be saved.",
    );
  });

  it("falls back to a nonjudgmental connection message for unknown errors", () => {
    expect(messageForError(new Error("network down"), "adjust the amount")).toBe(
      "We couldn't adjust the amount. Check your connection and try again.",
    );
  });

  it("never echoes an unknown error's own message (privacy: no value leak)", () => {
    const msg = messageForError(new Error("calories=9999999 rejected"), "load alternatives");
    expect(msg).not.toContain("9999999");
    expect(msg).toContain("load alternatives");
  });
});

describe("formatAmount", () => {
  it("renders an em dash for null", () => {
    expect(formatAmount(null)).toBe("—");
  });

  it("omits decimals for an integral amount", () => {
    expect(formatAmount(2)).toBe("2");
  });

  it("keeps one decimal for a fractional amount", () => {
    expect(formatAmount(1.5)).toBe("1.5");
  });
});

describe("SEARCH_DEBOUNCE_MS", () => {
  it("is the 300ms typing-pause window that bounds search fan-out", () => {
    expect(SEARCH_DEBOUNCE_MS).toBe(300);
  });
});

describe("isExactUpgradeEligible", () => {
  function src(source_type: ItemSourceDTO["source_type"], extra: Partial<ItemSourceDTO> = {}): ItemSourceDTO {
    return { source_type, label: "src", ref: `${source_type}:1`, ...extra };
  }
  function food(overrides: Partial<DerivedFoodItemDTO> = {}): DerivedFoodItemDTO {
    return {
      item_type: "food",
      id: "food-1",
      user_id: "user-1",
      log_event_id: "event-1",
      name: "Item",
      quantity_text: "1",
      unit: "serving",
      amount: 1,
      status: "resolved",
      grams: 10,
      calories: 100,
      protein_g: 5,
      carbs_g: 10,
      fat_g: 3,
      calories_estimated: 100,
      protein_g_estimated: 5,
      carbs_g_estimated: 10,
      fat_g_estimated: 3,
      source: src("model_prior"),
      is_edited: false,
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
      ...overrides,
    };
  }

  it("is true for model_prior and reference_source food", () => {
    expect(isExactUpgradeEligible(food({ source: src("model_prior") }))).toBe(true);
    expect(isExactUpgradeEligible(food({ source: src("reference_source") }))).toBe(true);
  });

  it("is true for a user_text item with a missing macro", () => {
    expect(
      isExactUpgradeEligible(food({ source: src("user_text"), carbs_g: null })),
    ).toBe(true);
  });

  it("is true for a user_text item with a non-null estimate_basis", () => {
    expect(
      isExactUpgradeEligible(
        food({ source: src("user_text", { estimate_basis: "comparable_reference" }) }),
      ),
    ).toBe(true);
  });

  it("is false for a fully-specified user_text item", () => {
    expect(isExactUpgradeEligible(food({ source: src("user_text") }))).toBe(false);
  });

  it("is false for already source-backed food sources", () => {
    for (const t of [
      "user_label",
      "product_database",
      "trusted_nutrition_database",
      "official_source",
    ] as const) {
      expect(isExactUpgradeEligible(food({ source: src(t) }))).toBe(false);
    }
  });

  it("is false for a food item with no source descriptor", () => {
    expect(isExactUpgradeEligible(food({ source: null }))).toBe(false);
  });

  it("is false for an exercise item", () => {
    const ex: DerivedExerciseItemDTO = {
      item_type: "exercise",
      id: "ex-1",
      user_id: "user-1",
      log_event_id: "event-2",
      name: "Run",
      quantity_text: "30 min",
      unit: "min",
      amount: 30,
      status: "resolved",
      active_calories: 300,
      active_calories_estimated: 300,
      source: null,
      is_edited: false,
      created_at: "2026-07-01T00:00:00Z",
      updated_at: "2026-07-01T00:00:00Z",
    };
    expect(isExactUpgradeEligible(ex)).toBe(false);
  });
});
