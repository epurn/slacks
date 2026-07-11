import type { DerivedExerciseItemDTO } from "@/api/derivedItems";

import { summaryMinusDeletedEvent } from "./helpers";
import { event, foodItem, summary } from "./todayTestUtils";

function exerciseItem(
  overrides: Partial<DerivedExerciseItemDTO> = {},
): DerivedExerciseItemDTO {
  return {
    item_type: "exercise",
    id: "ex-1",
    user_id: "user-1",
    log_event_id: "a",
    name: "Run",
    quantity_text: "30 min",
    unit: "min",
    amount: 30,
    status: "resolved",
    active_calories: 250,
    active_calories_estimated: 250,
    created_at: "2026-06-26T08:00:00Z",
    updated_at: "2026-06-26T08:00:00Z",
    ...overrides,
  };
}

// The local recompute must mirror the backend finalized-state filter
// (docs/contracts/daily-summary.md): only resolved items on a completed event
// count toward intake/burn; a needs_clarification event and each proposed food
// item are one uncounted unit; everything else contributes nothing.
describe("summaryMinusDeletedEvent (FTY-322)", () => {
  const base = summary({
    intake: { calories: 500, protein_g: 40, carbs_g: 50, fat_g: 20 },
    uncounted_entries: 2,
    exercise: { active_calories: 300 },
  });

  it("subtracts a completed event's resolved food items from intake", () => {
    const next = summaryMinusDeletedEvent(
      base,
      event({ id: "a", status: "completed" }),
      [foodItem({ calories: 150, protein_g: 20, carbs_g: 8, fat_g: 4 })],
    );
    expect(next.intake).toEqual({
      calories: 350,
      protein_g: 20,
      carbs_g: 42,
      fat_g: 16,
    });
    expect(next.uncounted_entries).toBe(2);
    expect(next.exercise.active_calories).toBe(300);
  });

  it("subtracts a resolved exercise item from the burn, not the intake", () => {
    const next = summaryMinusDeletedEvent(
      base,
      event({ id: "a", status: "completed" }),
      [exerciseItem({ active_calories: 250 })],
    );
    expect(next.exercise.active_calories).toBe(50);
    expect(next.intake).toEqual(base.intake);
  });

  it("counts a proposed food item as one uncounted unit, never as intake", () => {
    const next = summaryMinusDeletedEvent(
      base,
      event({ id: "a", status: "completed" }),
      [foodItem({ status: "proposed", calories: 999 })],
    );
    expect(next.intake).toEqual(base.intake);
    expect(next.uncounted_entries).toBe(1);
  });

  it("counts a needs_clarification event as one uncounted unit", () => {
    const next = summaryMinusDeletedEvent(
      base,
      event({ id: "a", status: "needs_clarification" }),
      [],
    );
    expect(next.intake).toEqual(base.intake);
    expect(next.uncounted_entries).toBe(1);
  });

  it("changes nothing for a pending event still being estimated", () => {
    const next = summaryMinusDeletedEvent(
      base,
      event({ id: "a", status: "pending" }),
      [foodItem({ calories: 150 })],
    );
    expect(next).toEqual(base);
  });

  it("clamps every figure at zero so local/server drift never shows a negative", () => {
    const next = summaryMinusDeletedEvent(
      summary({
        intake: { calories: 100, protein_g: 5, carbs_g: 5, fat_g: 5 },
        uncounted_entries: 0,
        exercise: { active_calories: 0 },
      }),
      event({ id: "a", status: "completed" }),
      [
        foodItem({ calories: 150, protein_g: 20, carbs_g: 8, fat_g: 50 }),
        exerciseItem({ active_calories: 250 }),
      ],
    );
    expect(next.intake).toEqual({ calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 });
    expect(next.exercise.active_calories).toBe(0);
    expect(next.uncounted_entries).toBe(0);
  });

  it("leaves date, target, and has_intake for the server to reconcile", () => {
    const next = summaryMinusDeletedEvent(
      base,
      event({ id: "a", status: "completed" }),
      [foodItem({ calories: 500, protein_g: 40, carbs_g: 50, fat_g: 20 })],
    );
    expect(next.date).toBe(base.date);
    expect(next.target).toEqual(base.target);
    expect(next.has_intake).toBe(base.has_intake);
  });
});
