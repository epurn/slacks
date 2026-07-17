/**
 * FTY-378: correction-sheet rename affordance.
 *
 * Sibling to `CorrectionSheet.test.tsx` (that file is pinned at the LOC
 * baseline). Covers the story's verification list with a mocked
 * `renameDerivedItem`:
 *   - rename affordance present for food and exercise items; opens the inline
 *     editor in place (sheet stays presented, no navigation);
 *   - open → edit → save calls the client with the trimmed name, updates the
 *     local + parent item, and fires the correction-saved beat;
 *   - empty / whitespace-only / unchanged draft disables Save;
 *   - API failure keeps the prior name, shows calm copy (never the typed
 *     name), and mutates nothing;
 *   - cancel restores the prior state;
 *   - accessibility labels on the entry point, field, and actions.
 */

import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { ThemeProvider } from "@/theme";

import {
  CorrectionSheet,
  type ClarificationData,
  type CorrectionSheetBaseProps,
} from "./CorrectionSheet";
import {
  DerivedItemApiError,
  type DerivedExerciseItemDTO,
  type DerivedFoodItemDTO,
  type ItemSourceDTO,
} from "@/api/derivedItems";
import type { ApiSession } from "@/state/session";
import { cleanupReactTestRenderers, trackReactTestRenderer } from "@/testUtils/reactTestRenderer";
import { mockReduceMotion } from "@/testUtils/reduceMotion";
import { correctionSavedHaptic } from "@/theme/haptics";

// The correction-saved beat's haptic is mocked so a successful commit can be
// asserted without a native Taptic Engine.
jest.mock("@/theme/haptics", () => ({
  correctionSavedHaptic: jest.fn(),
  entryResolvedHaptic: jest.fn(),
  targetReachedHaptic: jest.fn(),
}));

const mockCorrectionSavedHaptic = correctionSavedHaptic as jest.MockedFunction<
  typeof correctionSavedHaptic
>;

// expo-symbols is a native module — replace SymbolView with a View stub that
// exposes the symbol name via testID (same pattern as CorrectionSheet.test.tsx).
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

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "user-1",
};

function usdaSource(): ItemSourceDTO {
  return {
    source_type: "trusted_nutrition_database",
    label: "USDA",
    ref: "usda_fdc:168880",
  };
}

function food(overrides: Partial<DerivedFoodItemDTO> = {}): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: "food-1",
    user_id: "user-1",
    log_event_id: "event-1",
    name: "Turkey breast",
    quantity_text: "1 serving",
    unit: "serving",
    amount: 1,
    status: "resolved",
    grams: 85,
    calories: 120,
    protein_g: 26,
    carbs_g: 0,
    fat_g: 1,
    calories_estimated: 120,
    protein_g_estimated: 26,
    carbs_g_estimated: 0,
    fat_g_estimated: 1,
    source: usdaSource(),
    is_edited: false,
    is_renamed: false,
    created_at: "2026-06-28T08:00:00Z",
    updated_at: "2026-06-28T08:00:00Z",
    ...overrides,
  };
}

function exercise(
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
    active_calories: 300,
    active_calories_estimated: 300,
    source: null,
    is_edited: false,
    is_renamed: false,
    created_at: "2026-07-01T08:00:00Z",
    updated_at: "2026-07-01T08:00:00Z",
    ...overrides,
  };
}

const clarificationData: ClarificationData = {
  question: "What kind of milk?",
  options: ["Whole", "2%", "Skim"],
};

// ─── Test helpers ──────────────────────────────────────────────────────────────

function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(<ThemeProvider override="light">{element}</ThemeProvider>);
  });
  return trackReactTestRenderer(tree);
}

function allText(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

function findByLabel(tree: ReactTestRenderer, label: string) {
  return tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
}

function press(tree: ReactTestRenderer, label: string): void {
  act(() => {
    findByLabel(tree, label).props.onPress();
  });
}

async function pressAsync(tree: ReactTestRenderer, label: string): Promise<void> {
  const node = findByLabel(tree, label);
  await act(async () => {
    node.props.onPress();
  });
}

function nameInput(tree: ReactTestRenderer) {
  return tree.root.find(
    (n) =>
      n.props.accessibilityLabel === "Item name" &&
      typeof n.props.onChangeText === "function",
  );
}

function nameInputs(tree: ReactTestRenderer) {
  // `deep: false` collapses the composite TextInput and its host child into a
  // single match, mirroring what `find` does.
  return tree.root.findAll(
    (n) =>
      n.props.accessibilityLabel === "Item name" &&
      typeof n.props.onChangeText === "function",
    { deep: false },
  );
}

function typeName(tree: ReactTestRenderer, value: string): void {
  const node = nameInput(tree);
  act(() => {
    node.props.onChangeText(value);
  });
}

function defaultProps(overrides: Partial<CorrectionSheetBaseProps> = {}) {
  return {
    item: food(),
    visible: true,
    onClose: jest.fn(),
    session: SESSION,
    editItem: jest.fn(),
    renameItem: jest.fn(),
    listCandidates: jest.fn().mockResolvedValue([]),
    reResolve: jest.fn(),
    saveFood: jest.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  mockReduceMotion(false);
  mockCorrectionSavedHaptic.mockClear();
});

afterEach(() => {
  cleanupReactTestRenderers();
  jest.restoreAllMocks();
});

// ─── Affordance + open ─────────────────────────────────────────────────────────

describe("rename affordance", () => {
  it("is present on a food item and opens the inline editor seeded with the current name", () => {
    const tree = mount(<CorrectionSheet {...defaultProps()} />);
    press(tree, "Rename item");

    const input = nameInput(tree);
    expect(input.props.value).toBe("Turkey breast");
    // In place, no navigation: the same sheet is still presented — header name
    // and its Done affordance are still rendered around the editor.
    expect(allText(tree)).toContain("Turkey breast");
    expect(findByLabel(tree, "Close")).toBeTruthy();
  });

  it("is present on an exercise item too (unlike the food-gated numeric levers)", () => {
    const tree = mount(<CorrectionSheet {...defaultProps({ item: exercise() })} />);
    press(tree, "Rename item");
    expect(nameInput(tree).props.value).toBe("Running");
  });

  it("is inert in clarify mode", () => {
    const tree = mount(
      <CorrectionSheet
        {...defaultProps()}
        needsClarification
        clarificationData={clarificationData}
      />,
    );
    const affordance = findByLabel(tree, "Rename item");
    expect(affordance.props.disabled).toBe(true);
  });
});

// ─── Save ──────────────────────────────────────────────────────────────────────

describe("rename save", () => {
  it("calls renameDerivedItem with the trimmed name, updates sheet + parent, fires the beat", async () => {
    const updated = food({ name: "Herb roasted turkey", is_renamed: true });
    const renameItem = jest.fn().mockResolvedValue(updated);
    const onItemChange = jest.fn();
    const tree = mount(
      <CorrectionSheet {...defaultProps({ renameItem, onItemChange })} />,
    );

    press(tree, "Rename item");
    typeName(tree, "  Herb roasted turkey  ");
    await pressAsync(tree, "Save name");

    expect(renameItem).toHaveBeenCalledWith(
      SESSION,
      "food",
      "food-1",
      "Herb roasted turkey",
    );
    expect(onItemChange).toHaveBeenCalledWith(updated);
    // New name is visible in the sheet header; the editor has closed.
    expect(allText(tree)).toContain("Herb roasted turkey");
    expect(nameInputs(tree)).toHaveLength(0);
    expect(mockCorrectionSavedHaptic).toHaveBeenCalledTimes(1);
  });

  it("renames an exercise item through the exercise route", async () => {
    const updated = exercise({ name: "Trail running", is_renamed: true });
    const renameItem = jest.fn().mockResolvedValue(updated);
    const tree = mount(
      <CorrectionSheet {...defaultProps({ item: exercise(), renameItem })} />,
    );

    press(tree, "Rename item");
    typeName(tree, "Trail running");
    await pressAsync(tree, "Save name");

    expect(renameItem).toHaveBeenCalledWith(SESSION, "exercise", "ex-1", "Trail running");
    expect(allText(tree)).toContain("Trail running");
  });
});

// ─── Validation ────────────────────────────────────────────────────────────────

describe("rename validation", () => {
  it("disables Save for an unchanged draft, and for empty / whitespace-only drafts", () => {
    const renameItem = jest.fn();
    const tree = mount(<CorrectionSheet {...defaultProps({ renameItem })} />);
    press(tree, "Rename item");

    // Seeded (unchanged) draft: disabled.
    const save = () => findByLabel(tree, "Save name");
    expect(save().props.accessibilityState).toEqual({ disabled: true });

    // Whitespace-only: still disabled; a direct press commits nothing.
    typeName(tree, "   ");
    expect(save().props.accessibilityState).toEqual({ disabled: true });
    press(tree, "Save name");
    expect(renameItem).not.toHaveBeenCalled();

    // A real changed name enables Save.
    typeName(tree, "Roast turkey");
    expect(save().props.accessibilityState).toEqual({ disabled: false });
  });
});

// ─── Failure ───────────────────────────────────────────────────────────────────

describe("rename failure", () => {
  it("keeps the prior name, shows calm content-free copy, and mutates nothing", async () => {
    const renameItem = jest
      .fn()
      .mockRejectedValue(
        new DerivedItemApiError(422, "That value couldn't be saved. Check it and try again."),
      );
    const onItemChange = jest.fn();
    const tree = mount(
      <CorrectionSheet {...defaultProps({ renameItem, onItemChange })} />,
    );

    press(tree, "Rename item");
    typeName(tree, "Some private name");
    await pressAsync(tree, "Save name");

    // Prior name still shown; nothing propagated; no success beat.
    expect(allText(tree)).toContain("Turkey breast");
    expect(onItemChange).not.toHaveBeenCalled();
    expect(mockCorrectionSavedHaptic).not.toHaveBeenCalled();

    // The editor stays open for a retry, with the calm mapped copy — which
    // never echoes the typed name.
    expect(nameInputs(tree)).toHaveLength(1);
    const alert = tree.root.find((n) => n.props.accessibilityRole === "alert");
    expect(alert.props.children).toBe(
      "That value couldn't be saved. Check it and try again.",
    );
    expect(String(alert.props.children)).not.toContain("Some private name");
  });
});

// ─── Cancel ────────────────────────────────────────────────────────────────────

describe("rename cancel", () => {
  it("exits rename mode with no change and reseeds from the current name on reopen", () => {
    const renameItem = jest.fn();
    const tree = mount(<CorrectionSheet {...defaultProps({ renameItem })} />);

    press(tree, "Rename item");
    typeName(tree, "Abandoned draft");
    press(tree, "Cancel rename");

    expect(nameInputs(tree)).toHaveLength(0);
    expect(allText(tree)).toContain("Turkey breast");
    expect(renameItem).not.toHaveBeenCalled();

    // Reopening seeds from the item's (unchanged) name, not the abandoned draft.
    press(tree, "Rename item");
    expect(nameInput(tree).props.value).toBe("Turkey breast");
  });
});

// ─── Accessibility ─────────────────────────────────────────────────────────────

describe("rename accessibility", () => {
  it("labels the entry point, the text field, and the Save / Cancel actions", () => {
    const tree = mount(<CorrectionSheet {...defaultProps()} />);
    expect(findByLabel(tree, "Rename item")).toBeTruthy();

    press(tree, "Rename item");
    expect(nameInput(tree)).toBeTruthy();
    const save = findByLabel(tree, "Save name");
    const cancel = findByLabel(tree, "Cancel rename");
    expect(save.props.accessibilityRole).toBe("button");
    expect(cancel.props.accessibilityRole).toBe("button");
  });
});
