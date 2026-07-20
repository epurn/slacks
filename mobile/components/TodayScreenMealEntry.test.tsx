import { act } from "react-test-renderer";

import { TodayScreen } from "./TodayScreen";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

import {
  INACTIVE,
  SESSION,
  cleanupTrees,
  event,
  foodItem,
  hasA11yLabel,
  mount,
  press,
  pressByLabelPrefix,
  textContent,
} from "./today/todayTestUtils";

// FTY-420: a multi-item meal (one log event, several derived items) renders as a
// single collapsed Today row — the event's model-generated name + the summed
// total — that expands on tap into an editable per-item breakdown.

jest.mock("@/theme/haptics", () => ({
  entryResolvedHaptic: jest.fn(),
  correctionSavedHaptic: jest.fn(),
  targetReachedHaptic: jest.fn(),
}));

jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactNative = require("react-native");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  return {
    SymbolView: ({ name, accessibilityLabel }: { name: string; accessibilityLabel?: string }) =>
      ReactLib.createElement(ReactNative.View, {
        testID: `sf-symbol-${String(name)}`,
        accessibilityLabel,
      }),
  };
});

jest.mock("expo-camera", () => ({
  useCameraPermissions: jest.fn(() => [
    { status: "granted", granted: true, canAskAgain: false, expires: "never" },
    jest.fn().mockResolvedValue({ status: "granted", granted: true }),
    jest.fn().mockResolvedValue({ status: "granted", granted: true }),
  ]),
  CameraView: jest.fn(() => null),
}));

jest.mock("expo-linking", () => ({
  openSettings: jest.fn().mockResolvedValue(undefined),
}));

jest.mock("@/api/logEvents", () => {
  const actual = jest.requireActual("@/api/logEvents");
  return {
    ...actual,
    listTodayLogEventEntries: jest.fn().mockResolvedValue([]),
  };
});

beforeEach(() => mockReduceMotion(false));
afterEach(cleanupTrees);

// A turkey (100 kcal) + a sub bun (150 kcal) — the classic composite meal.
const turkey = foodItem({
  id: "item-1",
  name: "Turkey",
  quantity_text: "2 oz",
  calories: 100,
  protein_g: 14,
  carbs_g: 0,
  fat_g: 4,
});
const bun = foodItem({
  id: "item-2",
  name: "Sub bun",
  quantity_text: "half",
  calories: 150,
  protein_g: 5,
  carbs_g: 30,
  fat_g: 2,
});

function mountMeal(overrides: {
  name?: string | null;
  raw_text?: string;
  editItem?: jest.Mock;
}) {
  const load = jest.fn().mockResolvedValue([
    event({
      id: "a",
      raw_text: overrides.raw_text ?? "turkey on a sub bun",
      // Respect an explicit `null` (fallback case); default to a real name.
      name: "name" in overrides ? overrides.name : "Turkey sandwich",
      status: "completed",
    }),
  ]);
  return mount(
    <TodayScreen
      session={SESSION}
      load={load}
      editItem={overrides.editItem}
      items={{ a: [turkey, bun] }}
      useActive={INACTIVE}
    />,
  );
}

describe("TodayScreen composite meal entry (FTY-420)", () => {
  it("renders a multi-item meal as ONE collapsed row using event.name + the summed total", async () => {
    const tree = mountMeal({ name: "Turkey sandwich" });
    await act(async () => {});

    // One row: the model-generated meal name and the summed total (100 + 150).
    expect(hasA11yLabel(tree, "Turkey sandwich, 250 kcal total, 2 items")).toBe(true);
    // The per-item breakdown is collapsed — the items are not N loose rows yet.
    expect(textContent(tree)).not.toContain("Sub bun");
    expect(
      tree.root.findAll((n) => n.props.testID === "meal-breakdown-a-item-2").length,
    ).toBe(0);
  });

  it("falls back to the raw phrase (never a blank row) when event.name is null", async () => {
    const tree = mountMeal({
      name: null,
      raw_text: "half a 300 calorie sub bun with turkey",
    });
    await act(async () => {});

    expect(
      hasA11yLabel(
        tree,
        "half a 300 calorie sub bun with turkey, 250 kcal total, 2 items",
      ),
    ).toBe(true);
  });

  it("expands the per-item breakdown on tap (food + portion + calories/macros) and collapses again", async () => {
    const tree = mountMeal({ name: "Turkey sandwich" });
    await act(async () => {});

    press(tree, "Turkey sandwich, 250 kcal total, 2 items");

    // Each breakdown row shows the food, its portion, its calories and macros.
    const expanded = textContent(tree);
    expect(expanded).toContain("Sub bun");
    expect(expanded).toContain("half"); // portion
    expect(expanded).toContain("150 kcal");
    expect(expanded).toContain("P 5g · C 30g · F 2g"); // macros
    expect(hasA11yLabel(tree, "Sub bun, half · P 5g · C 30g · F 2g, 150 kcal")).toBe(
      true,
    );

    // Tapping the meal row again collapses the breakdown.
    press(tree, "Turkey sandwich, 250 kcal total, 2 items");
    expect(textContent(tree)).not.toContain("Sub bun");
  });

  it("opens the edit flow for a breakdown item and the collapsed total re-sums after the edit", async () => {
    // The server re-costs the bun to 200 kcal after a portion bump; the meal
    // total must follow (100 + 200 = 300), proving total == sum of items.
    const editItem = jest.fn().mockResolvedValue(
      foodItem({
        id: "item-2",
        log_event_id: "a",
        name: "Sub bun",
        quantity_text: "1",
        calories: 200,
        protein_g: 5,
        carbs_g: 30,
        fat_g: 2,
      }),
    );
    const tree = mountMeal({ name: "Turkey sandwich", editItem });
    await act(async () => {});

    press(tree, "Turkey sandwich, 250 kcal total, 2 items");
    // Tap the bun's breakdown row → the existing item edit / correction sheet.
    pressByLabelPrefix(tree, "Sub bun,");
    expect(hasA11yLabel(tree, "Increase amount")).toBe(true);

    await act(async () => {
      press(tree, "Increase amount");
    });
    expect(editItem).toHaveBeenCalledTimes(1);
    const [, itemType, itemId] = editItem.mock.calls[0];
    expect(itemType).toBe("food");
    expect(itemId).toBe("item-2");

    press(tree, "Close");

    // The collapsed meal total re-sums to reflect the re-costed item.
    expect(hasA11yLabel(tree, "Turkey sandwich, 300 kcal total, 2 items")).toBe(true);
  });
});
