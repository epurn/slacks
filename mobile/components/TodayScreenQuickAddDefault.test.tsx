import { act } from "react-test-renderer";

import { TodayScreen } from "./TodayScreen";
import { type FoodSuggestionDTO } from "@/api/foodSuggestions";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

import {
  SESSION,
  cleanupTrees,
  event,
  hasA11yLabel,
  inputValue,
  mount,
  press,
  savedFood,
  summary,
  typeInto,
} from "./today/todayTestUtils";

/**
 * FTY-408: Quick-add defaults to the user's corrected entry for a known food.
 *
 * Drives the real TodayScreen: a food the user has logged/corrected before is a
 * history-only suggestion (`saved_food_id === null`); typing its name surfaces
 * it as the "From your log" default below the composer, tapping it prefills the
 * composer (never a one-tap log), and the subsequent submit routes through the
 * estimator — where FTY-406's prior-correction tier resolves the corrected
 * value. A typed name with no matching history surfaces no default and leaves
 * the composer untouched (no regression).
 */

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
    SymbolView: ({
      name,
      accessibilityLabel,
    }: {
      name: string;
      accessibilityLabel?: string;
    }) =>
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

// Keep the item-forward by-date feed hermetic: an empty day unless a test
// drives an entry itself.
jest.mock("@/api/logEvents", () => {
  const actual = jest.requireActual("@/api/logEvents");
  return {
    ...actual,
    listTodayLogEventEntries: jest.fn().mockResolvedValue([]),
  };
});

const ACTIVE = () => true;

// A food the user has corrected before: it lives in completed history, so the
// FTY-340 pool returns it as a history-only suggestion (no saved_food_id).
const CORRECTED_HISTORY: FoodSuggestionDTO = {
  label: "Black coffee",
  submit_phrase: "black coffee",
  saved_food_id: null,
  score: 2,
};

const DEFAULT_LABEL = "Quick-add from your log: Black coffee";

beforeEach(() => mockReduceMotion(false));
afterEach(cleanupTrees);

describe("TodayScreen quick-add default (FTY-408)", () => {
  it("surfaces the prior food as a default when the typed name matches, and quick-adding it logs through the estimator", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const searchSavedFoods = jest.fn();
    const create = jest
      .fn()
      .mockResolvedValue(
        event({ id: "server-1", raw_text: "black coffee", status: "pending" }),
      );
    const getSuggestions = jest
      .fn()
      .mockResolvedValue({ items: [CORRECTED_HISTORY], limit: 8 });

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        searchSavedFoods={searchSavedFoods}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
        getSuggestions={getSuggestions}
        useActive={ACTIVE}
      />,
    );
    await act(async () => {});

    // No default while the composer is empty.
    expect(hasA11yLabel(tree, DEFAULT_LABEL)).toBe(false);

    // Typing the known name surfaces the prior food as the default.
    typeInto(tree, "Log food or exercise", "black coffee");
    expect(hasA11yLabel(tree, DEFAULT_LABEL)).toBe(true);

    // Tapping the default prefills the composer — deliberate, not a one-tap log.
    await act(async () => {
      press(tree, DEFAULT_LABEL);
    });
    expect(inputValue(tree, "Log food or exercise")).toBe("black coffee");
    expect(create).not.toHaveBeenCalled();
    // A history-only prior food never routes through the saved-food skip path.
    expect(searchSavedFoods).not.toHaveBeenCalled();

    // Add submits through the estimator (where FTY-406 resolves the correction):
    // the raw phrase is sent and a pending skeleton shows — no synthetic value.
    await act(async () => {
      press(tree, "Add entry");
    });
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "black coffee",
      expect.any(String),
    );
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
  });

  it("matches name-normalized, so a differently-cased/spaced name still surfaces the default", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const getSuggestions = jest
      .fn()
      .mockResolvedValue({ items: [CORRECTED_HISTORY], limit: 8 });

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
        getSuggestions={getSuggestions}
        useActive={ACTIVE}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "  BLACK   Coffee");
    expect(hasA11yLabel(tree, DEFAULT_LABEL)).toBe(true);
  });

  it("surfaces no default when the typed name has no matching history (no regression)", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const getSuggestions = jest
      .fn()
      .mockResolvedValue({ items: [CORRECTED_HISTORY], limit: 8 });

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
        getSuggestions={getSuggestions}
        useActive={ACTIVE}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "pad thai");
    expect(hasA11yLabel(tree, DEFAULT_LABEL)).toBe(false);
    expect(tree.root.findAll((n) => n.props.testID === "quick-add-default")).toHaveLength(0);
    // The composer keeps exactly what the user typed.
    expect(inputValue(tree, "Log food or exercise")).toBe("pad thai");
  });

  it("does not surface a saved food as a default — those are the saved-food typeahead's job", async () => {
    const load = jest.fn().mockResolvedValue([]);
    // A saved food carries a saved_food_id, so it is excluded from the default.
    const savedSuggestion: FoodSuggestionDTO = {
      label: "Greek yogurt",
      submit_phrase: "greek yogurt",
      saved_food_id: "sf-1",
      score: 3,
    };
    const searchSavedFoods = jest
      .fn()
      .mockResolvedValue({ items: [savedFood({ id: "sf-1", name: "Greek yogurt" })], limit: 20 });
    const getSuggestions = jest
      .fn()
      .mockResolvedValue({ items: [savedSuggestion], limit: 8 });

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        searchSavedFoods={searchSavedFoods}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
        getSuggestions={getSuggestions}
        useActive={ACTIVE}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "greek yogurt");
    expect(
      hasA11yLabel(tree, "Quick-add from your log: Greek yogurt"),
    ).toBe(false);
  });
});
