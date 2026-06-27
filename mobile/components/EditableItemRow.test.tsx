import { act, create as render, type ReactTestRenderer } from "react-test-renderer";

import { EditableItemRow } from "./EditableItemRow";
import {
  DerivedItemApiError,
  type DerivedExerciseItemDTO,
  type DerivedFoodItemDTO,
} from "@/api/derivedItems";
import { SavedFoodApiError, type SavedFoodDTO } from "@/api/savedFoods";
import type { ApiSession } from "@/state/session";

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "u1",
};

function food(overrides: Partial<DerivedFoodItemDTO> = {}): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: "food-1",
    user_id: "u1",
    log_event_id: "e1",
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
    created_at: "2026-06-26T08:00:00Z",
    updated_at: "2026-06-26T08:00:00Z",
    ...overrides,
  };
}

function exercise(
  overrides: Partial<DerivedExerciseItemDTO> = {},
): DerivedExerciseItemDTO {
  return {
    item_type: "exercise",
    id: "ex-1",
    user_id: "u1",
    log_event_id: "e1",
    name: "Running",
    quantity_text: "30 min",
    unit: "min",
    amount: 30,
    status: "resolved",
    active_calories: 300,
    active_calories_estimated: 300,
    created_at: "2026-06-26T08:00:00Z",
    updated_at: "2026-06-26T08:00:00Z",
    ...overrides,
  };
}

function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(element);
  });
  return tree;
}

function textContent(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

function hasA11yLabel(tree: ReactTestRenderer, label: string): boolean {
  return tree.root.findAll((n) => n.props.accessibilityLabel === label).length > 0;
}

function a11yLabels(tree: ReactTestRenderer): string[] {
  return tree.root
    .findAll((n) => typeof n.props.accessibilityLabel === "string")
    .map((n) => n.props.accessibilityLabel as string);
}

function press(tree: ReactTestRenderer, label: string): void {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
  act(() => {
    node.props.onPress();
  });
}

async function pressAsync(tree: ReactTestRenderer, label: string): Promise<void> {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
  await act(async () => {
    node.props.onPress();
  });
}

function typeInto(tree: ReactTestRenderer, label: string, value: string): void {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onChangeText === "function",
  );
  act(() => {
    node.props.onChangeText(value);
  });
}

describe("EditableItemRow rendering", () => {
  it("renders an edit control for every editable food field", () => {
    const tree = mount(<EditableItemRow item={food()} session={SESSION} />);
    for (const label of ["Edit Servings", "Edit Calories", "Edit Protein", "Edit Carbs", "Edit Fat"]) {
      expect(hasA11yLabel(tree, label)).toBe(true);
    }
    expect(textContent(tree)).toContain("Greek yogurt");
  });

  it("renders only the burn control for an exercise item", () => {
    const tree = mount(<EditableItemRow item={exercise()} session={SESSION} />);
    expect(hasA11yLabel(tree, "Edit Burn")).toBe(true);
    expect(hasA11yLabel(tree, "Edit Calories")).toBe(false);
  });

  it("skips a field with no resolved value", () => {
    const tree = mount(
      <EditableItemRow item={food({ fat_g: null, fat_g_estimated: null })} session={SESSION} />,
    );
    expect(hasA11yLabel(tree, "Edit Fat")).toBe(false);
    expect(hasA11yLabel(tree, "Edit Calories")).toBe(true);
  });
});

describe("edited-vs-estimated indicator", () => {
  it("shows an accessible edited indicator naming the original estimate", () => {
    const tree = mount(
      <EditableItemRow
        item={food({ calories: 200, calories_estimated: 150 })}
        session={SESSION}
      />,
    );
    // Visible, non-color text marker plus the preserved original.
    const content = textContent(tree);
    expect(content).toContain("Edited");
    expect(content).toContain("was 150");
    // Conveyed non-visually: the value's accessibility label states the edit.
    expect(
      a11yLabels(tree).some((l) => l === "Calories 200 cal, edited from 150 cal"),
    ).toBe(true);
  });

  it("does not mark an unedited field", () => {
    const tree = mount(<EditableItemRow item={food()} session={SESSION} />);
    expect(textContent(tree)).not.toContain("Edited");
    expect(a11yLabels(tree)).toContain("Calories 150 cal");
  });
});

describe("editing a derived item", () => {
  it("overrides a single field and re-renders the server's value with an edited indicator", async () => {
    const edit = jest
      .fn()
      .mockResolvedValue(food({ calories: 200, calories_estimated: 150 }));
    const onItemChange = jest.fn();
    const tree = mount(
      <EditableItemRow item={food()} session={SESSION} edit={edit} onItemChange={onItemChange} />,
    );

    press(tree, "Edit Calories");
    typeInto(tree, "Calories value", "200");
    await pressAsync(tree, "Save Calories");

    expect(edit).toHaveBeenCalledWith(SESSION, "food", "food-1", "calories", 200);
    expect(onItemChange).toHaveBeenCalledWith(
      expect.objectContaining({ id: "food-1", calories: 200 }),
    );
    const content = textContent(tree);
    expect(content).toContain("200");
    expect(content).toContain("Edited");
    expect(content).toContain("was 150");
  });

  it("shows the edited value optimistically before the server responds", async () => {
    let resolveEdit!: (item: DerivedFoodItemDTO) => void;
    const edit = jest.fn().mockReturnValue(
      new Promise<DerivedFoodItemDTO>((resolve) => {
        resolveEdit = resolve;
      }),
    );
    const tree = mount(<EditableItemRow item={food()} session={SESSION} edit={edit} />);

    press(tree, "Edit Calories");
    typeInto(tree, "Calories value", "180");
    press(tree, "Save Calories");

    // Optimistic: 180 shows immediately, before the PATCH resolves.
    expect(textContent(tree)).toContain("180");

    await act(async () => {
      resolveEdit(food({ calories: 180, calories_estimated: 150 }));
    });
    expect(textContent(tree)).toContain("was 150");
  });

  it("renders server-rescaled calories/macros from a servings edit without computing them", async () => {
    // Doubling servings: the server returns rescaled calories/macros; the UI
    // re-renders exactly those values and marks the rescaled fields edited.
    const rescaled = food({
      amount: 2,
      calories: 300,
      protein_g: 40,
      carbs_g: 16,
      fat_g: 8,
      // estimates stay at the original 1-serving values
      calories_estimated: 150,
      protein_g_estimated: 20,
      carbs_g_estimated: 8,
      fat_g_estimated: 4,
    });
    const edit = jest.fn().mockResolvedValue(rescaled);
    const tree = mount(<EditableItemRow item={food()} session={SESSION} edit={edit} />);

    press(tree, "Edit Servings");
    typeInto(tree, "Servings value", "2");
    await pressAsync(tree, "Save Servings");

    expect(edit).toHaveBeenCalledWith(SESSION, "food", "food-1", "quantity", 2);
    const content = textContent(tree);
    expect(content).toContain("300"); // rescaled calories
    expect(content).toContain("40"); // rescaled protein
    expect(content).toContain("was 150"); // calories edited from original
    expect(content).toContain("was 20"); // protein edited from original
  });

  it("rolls back to the prior value and surfaces an error when the PATCH fails", async () => {
    const edit = jest
      .fn()
      .mockRejectedValue(new DerivedItemApiError(422, "That value couldn't be saved."));
    const onItemChange = jest.fn();
    const tree = mount(
      <EditableItemRow item={food()} session={SESSION} edit={edit} onItemChange={onItemChange} />,
    );

    press(tree, "Edit Calories");
    typeInto(tree, "Calories value", "999");
    await pressAsync(tree, "Save Calories");

    const content = textContent(tree);
    expect(content).toContain("That value couldn't be saved.");
    // Rolled back to the original; the optimistic 999 is gone and no edit lifted.
    expect(content).not.toContain("999");
    expect(content).toContain("150");
    expect(onItemChange).not.toHaveBeenCalled();
  });

  it("rejects a negative or non-numeric value locally without calling the endpoint", async () => {
    const edit = jest.fn();
    const tree = mount(<EditableItemRow item={food()} session={SESSION} edit={edit} />);

    press(tree, "Edit Calories");
    typeInto(tree, "Calories value", "-5");
    await pressAsync(tree, "Save Calories");

    expect(edit).not.toHaveBeenCalled();
    expect(textContent(tree)).toContain("zero or more");
  });

  it("cancels an edit without calling the endpoint", () => {
    const edit = jest.fn();
    const tree = mount(<EditableItemRow item={food()} session={SESSION} edit={edit} />);

    press(tree, "Edit Calories");
    typeInto(tree, "Calories value", "999");
    press(tree, "Cancel editing Calories");

    expect(edit).not.toHaveBeenCalled();
    expect(textContent(tree)).toContain("150");
    expect(textContent(tree)).not.toContain("999");
  });

  it("edits exercise burn through the active_calories field", async () => {
    const edit = jest
      .fn()
      .mockResolvedValue(exercise({ active_calories: 250, active_calories_estimated: 300 }));
    const tree = mount(<EditableItemRow item={exercise()} session={SESSION} edit={edit} />);

    press(tree, "Edit Burn");
    typeInto(tree, "Burn value", "250");
    await pressAsync(tree, "Save Burn");

    expect(edit).toHaveBeenCalledWith(SESSION, "exercise", "ex-1", "active_calories", 250);
    expect(textContent(tree)).toContain("was 300");
  });
});

// ─── Save this food action (FTY-053) ─────────────────────────────────────────

function savedFoodResult(overrides: Partial<SavedFoodDTO> = {}): SavedFoodDTO {
  return {
    id: "saved-1",
    user_id: SESSION.userId,
    name: "Greek yogurt",
    calories: 150,
    protein_g: 20,
    carbs_g: 8,
    fat_g: 4,
    serving_size: 1,
    serving_unit: "cup",
    source: "saved_from_correction",
    created_at: "2026-06-27T10:00:00Z",
    updated_at: "2026-06-27T10:00:00Z",
    ...overrides,
  };
}

describe("Save this food action", () => {
  it("shows the Save this food button when logPhrase is provided for a resolved food item", () => {
    const tree = mount(
      <EditableItemRow
        item={food()}
        session={SESSION}
        logPhrase="a cup of greek yogurt"
      />,
    );
    expect(hasA11yLabel(tree, "Save this food")).toBe(true);
  });

  it("does not show the Save this food button without logPhrase", () => {
    const tree = mount(<EditableItemRow item={food()} session={SESSION} />);
    expect(hasA11yLabel(tree, "Save this food")).toBe(false);
  });

  it("does not show the Save this food button for an exercise item", () => {
    const tree = mount(
      <EditableItemRow
        item={exercise()}
        session={SESSION}
        logPhrase="30 min run"
      />,
    );
    expect(hasA11yLabel(tree, "Save this food")).toBe(false);
  });

  it("does not show the Save this food button when calories are not resolved", () => {
    const tree = mount(
      <EditableItemRow
        item={food({ calories: null, calories_estimated: null })}
        session={SESSION}
        logPhrase="greek yogurt"
      />,
    );
    expect(hasA11yLabel(tree, "Save this food")).toBe(false);
  });

  it("calls saveFood with name, phrase, and the item's current nutrition snapshot", async () => {
    const saveFood = jest.fn().mockResolvedValue(savedFoodResult());
    const onSaved = jest.fn();
    const tree = mount(
      <EditableItemRow
        item={food()}
        session={SESSION}
        logPhrase="a cup of greek yogurt"
        saveFood={saveFood}
        onSaved={onSaved}
      />,
    );

    await pressAsync(tree, "Save this food");

    expect(saveFood).toHaveBeenCalledWith(
      SESSION,
      {
        name: "Greek yogurt",
        phrase: "a cup of greek yogurt",
        nutrition: {
          calories: 150,
          protein_g: 20,
          carbs_g: 8,
          fat_g: 4,
          serving_size: 1,
          serving_unit: "cup",
        },
      },
    );
    expect(onSaved).toHaveBeenCalledWith(savedFoodResult());
  });

  it("shows a success state and disables the button after a successful save", async () => {
    const saveFood = jest.fn().mockResolvedValue(savedFoodResult());
    const tree = mount(
      <EditableItemRow
        item={food()}
        session={SESSION}
        logPhrase="greek yogurt"
        saveFood={saveFood}
      />,
    );

    await pressAsync(tree, "Save this food");

    const content = textContent(tree);
    expect(content).toContain("Saved");
    // Button is disabled after save.
    const btn = tree.root.find(
      (n) => n.props.accessibilityLabel === "Save this food",
    );
    expect(btn.props.accessibilityState?.disabled).toBe(true);
  });

  it("surfaces a nonjudgmental error when the save fails", async () => {
    const saveFood = jest
      .fn()
      .mockRejectedValue(new SavedFoodApiError(422, "Validation error"));
    const tree = mount(
      <EditableItemRow
        item={food()}
        session={SESSION}
        logPhrase="greek yogurt"
        saveFood={saveFood}
      />,
    );

    await pressAsync(tree, "Save this food");

    const content = textContent(tree);
    expect(content).toContain("couldn't save that food");
    // Error does not echo validation error text or the phrase.
    expect(content).not.toContain("Validation error");
    // Button should be enabled to retry.
    const btn = tree.root.find(
      (n) => n.props.accessibilityLabel === "Save this food",
    );
    expect(btn.props.accessibilityState?.disabled).toBe(false);
  });

  it("uses amount and unit from the item as serving_size and serving_unit", async () => {
    const saveFood = jest.fn().mockResolvedValue(savedFoodResult());
    const tree = mount(
      <EditableItemRow
        item={food({ amount: 2, unit: "bowl" })}
        session={SESSION}
        logPhrase="2 bowls greek yogurt"
        saveFood={saveFood}
      />,
    );

    await pressAsync(tree, "Save this food");

    const [, request] = saveFood.mock.calls[0] as [unknown, { nutrition: { serving_size: number; serving_unit: string } }];
    expect(request.nutrition.serving_size).toBe(2);
    expect(request.nutrition.serving_unit).toBe("bowl");
  });

  it("falls back to serving_size=1 and serving_unit='serving' when amount/unit are null", async () => {
    const saveFood = jest.fn().mockResolvedValue(savedFoodResult());
    const tree = mount(
      <EditableItemRow
        item={food({ amount: null, unit: null })}
        session={SESSION}
        logPhrase="greek yogurt"
        saveFood={saveFood}
      />,
    );

    await pressAsync(tree, "Save this food");

    const [, request] = saveFood.mock.calls[0] as [unknown, { nutrition: { serving_size: number; serving_unit: string } }];
    expect(request.nutrition.serving_size).toBe(1);
    expect(request.nutrition.serving_unit).toBe("serving");
  });
});
