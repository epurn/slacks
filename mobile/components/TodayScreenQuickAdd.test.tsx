import { act } from "react-test-renderer";

import { TodayScreen } from "./TodayScreen";
import { type FoodSuggestionDTO } from "@/api/foodSuggestions";
import { type LogEventDTO } from "@/api/logEvents";
import { type SavedFoodSearchResponse } from "@/api/savedFoods";
import { TypeaheadSuggestionBar } from "@/components/TypeaheadSuggestionBar";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

import {
  INACTIVE,
  SESSION,
  cleanupTrees,
  event,
  hasA11yLabel,
  inputValue,
  mount,
  press,
  savedFood,
  summary,
  textContent,
} from "./today/todayTestUtils";

/**
 * FTY-341: Today quick-add suggestion chips. Proves the full flow against the
 * real TodayScreen: the FTY-340 ranking renders as a chip row above the composer
 * in server order, a chip tap prefills + focuses the composer (never a one-tap
 * log), a saved-food chip's subsequent submit skips the estimator (FTY-053
 * apply path), a history chip takes the normal estimator submit, the row is
 * focus-gated + refreshes after a submit, and a zero/failed fetch renders no row.
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

// Keep the item-forward by-date feed hermetic (FTY-198): an empty day unless a
// test drives an entry itself.
jest.mock("@/api/logEvents", () => {
  const actual = jest.requireActual("@/api/logEvents");
  return {
    ...actual,
    listTodayLogEventEntries: jest.fn().mockResolvedValue([]),
  };
});

const ACTIVE = () => true;

const SAVED_SUGGESTION: FoodSuggestionDTO = {
  label: "Greek yogurt",
  submit_phrase: "my usual yogurt",
  saved_food_id: "sf-1",
  score: 3,
};
const HISTORY_SUGGESTION: FoodSuggestionDTO = {
  label: "Black coffee",
  submit_phrase: "black coffee",
  saved_food_id: null,
  score: 1,
};

function suggestionLabels(tree: ReturnType<typeof mount>): string[] {
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

beforeEach(() => mockReduceMotion(false));
afterEach(cleanupTrees);

describe("TodayScreen quick-add suggestion chips (FTY-341)", () => {
  it("renders the chip row above the composer in canonical server order when focused", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const getSuggestions = jest.fn().mockResolvedValue({
      items: [SAVED_SUGGESTION, HISTORY_SUGGESTION],
      limit: 8,
    });
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

    expect(getSuggestions).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
    );
    expect(suggestionLabels(tree)).toEqual([
      "Suggestion: Greek yogurt",
      "Suggestion: Black coffee",
    ]);
  });

  it("does not fetch or render the row while the screen is not focused", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const getSuggestions = jest.fn().mockResolvedValue({
      items: [SAVED_SUGGESTION],
      limit: 8,
    });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getSuggestions={getSuggestions}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // Focus-gated (not a timer): an unfocused screen never fetches suggestions.
    expect(getSuggestions).not.toHaveBeenCalled();
    expect(suggestionLabels(tree)).toHaveLength(0);
  });

  it("renders no row when there are zero suggestions, leaving the composer usable", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const getSuggestions = jest.fn().mockResolvedValue({ items: [], limit: 8 });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getSuggestions={getSuggestions}
        useActive={ACTIVE}
      />,
    );
    await act(async () => {});

    expect(getSuggestions).toHaveBeenCalled();
    expect(suggestionLabels(tree)).toHaveLength(0);
    // Composer is still fully present and usable.
    expect(hasA11yLabel(tree, "Log food or exercise")).toBe(true);
  });

  it("renders no row and never blocks the composer when the fetch fails", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const getSuggestions = jest.fn().mockRejectedValue(new Error("network"));
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getSuggestions={getSuggestions}
        useActive={ACTIVE}
      />,
    );
    await act(async () => {});

    expect(suggestionLabels(tree)).toHaveLength(0);
    expect(hasA11yLabel(tree, "Log food or exercise")).toBe(true);
  });

  it("prefills + focuses the composer on chip tap without logging (no one-tap log)", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const create = jest.fn();
    const getSuggestions = jest
      .fn()
      .mockResolvedValue({ items: [HISTORY_SUGGESTION], limit: 8 });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        getSuggestions={getSuggestions}
        useActive={ACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "Suggestion: Black coffee");
    });

    // The phrase is in the composer, ready to submit — but nothing was logged.
    expect(inputValue(tree, "Log food or exercise")).toBe("black coffee");
    expect(create).not.toHaveBeenCalled();
  });

  it("routes a saved-food chip's submit through the estimator-skip apply path", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const yogurt = savedFood({ id: "sf-1", name: "Greek yogurt", calories: 200 });
    const searchSavedFoods = jest
      .fn()
      .mockResolvedValue({ items: [yogurt], limit: 20 });
    let resolveCreate!: (dto: LogEventDTO) => void;
    const create = jest.fn().mockReturnValue(
      new Promise<LogEventDTO>((resolve) => {
        resolveCreate = resolve;
      }),
    );
    const getSuggestions = jest
      .fn()
      .mockResolvedValue({ items: [SAVED_SUGGESTION], limit: 8 });

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        searchSavedFoods={searchSavedFoods}
        getSuggestions={getSuggestions}
        useActive={ACTIVE}
      />,
    );
    await act(async () => {});

    // Tap the saved-food chip → prefill + hydrate the saved food by id.
    await act(async () => {
      press(tree, "Suggestion: Greek yogurt");
    });
    expect(inputValue(tree, "Log food or exercise")).toBe("my usual yogurt");
    expect(searchSavedFoods).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "Greek yogurt",
    );

    // The subsequent submit skips the estimator: the saved food's nutrition
    // shows immediately as a synthetic resolved item (FTY-053).
    press(tree, "Add entry");
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "my usual yogurt",
      expect.any(String),
    );
    const content = textContent(tree);
    expect(content).toContain("Greek yogurt");
    expect(content).toContain("200");
    // Not a pending estimator skeleton — it resolved in place.
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(false);

    await act(async () => {
      resolveCreate(
        event({ id: "server-1", raw_text: "my usual yogurt", status: "pending" }),
      );
    });
    expect(textContent(tree)).toContain("200");
  });

  it("still takes the estimator-skip path when Add is tapped before the hydration resolves", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const yogurt = savedFood({ id: "sf-1", name: "Greek yogurt", calories: 200 });
    // The saved-food lookup stays in flight until the test resolves it — the
    // exact window where a fast tap + Add used to fall back to the estimator.
    let resolveLookup!: (response: SavedFoodSearchResponse) => void;
    const searchSavedFoods = jest.fn().mockReturnValue(
      new Promise<SavedFoodSearchResponse>((resolve) => {
        resolveLookup = resolve;
      }),
    );
    let resolveCreate!: (dto: LogEventDTO) => void;
    const create = jest.fn().mockReturnValue(
      new Promise<LogEventDTO>((resolve) => {
        resolveCreate = resolve;
      }),
    );
    const getSuggestions = jest
      .fn()
      .mockResolvedValue({ items: [SAVED_SUGGESTION], limit: 8 });

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        searchSavedFoods={searchSavedFoods}
        getSuggestions={getSuggestions}
        useActive={ACTIVE}
      />,
    );
    await act(async () => {});

    // Tap the chip and Add back-to-back, without letting the lookup resolve.
    press(tree, "Suggestion: Greek yogurt");
    press(tree, "Add entry");

    // The submit joined the in-flight hydration instead of racing past it.
    expect(create).not.toHaveBeenCalled();

    await act(async () => {
      resolveLookup({ items: [yogurt], limit: 20 });
    });

    // Once hydrated, the joined submit went out with the saved food attached:
    // synthetic resolved item, no estimator skeleton (FTY-053 skip path).
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "my usual yogurt",
      expect.any(String),
    );
    expect(textContent(tree)).toContain("200");
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(false);

    await act(async () => {
      resolveCreate(
        event({ id: "server-4", raw_text: "my usual yogurt", status: "pending" }),
      );
    });
    expect(textContent(tree)).toContain("200");
  });

  it("drops a superseded chip's late hydration when another chip is tapped before submit", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const yogurt = savedFood({ id: "sf-1", name: "Greek yogurt", calories: 200 });
    let resolveLookup!: (response: SavedFoodSearchResponse) => void;
    const searchSavedFoods = jest.fn().mockReturnValue(
      new Promise<SavedFoodSearchResponse>((resolve) => {
        resolveLookup = resolve;
      }),
    );
    const create = jest
      .fn()
      .mockResolvedValue(
        event({ id: "server-5", raw_text: "black coffee", status: "pending" }),
      );
    const getSuggestions = jest.fn().mockResolvedValue({
      items: [SAVED_SUGGESTION, HISTORY_SUGGESTION],
      limit: 8,
    });

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        searchSavedFoods={searchSavedFoods}
        getSuggestions={getSuggestions}
        useActive={ACTIVE}
      />,
    );
    await act(async () => {});

    // Saved-food chip first (lookup in flight), then a history chip replaces
    // the composer text before the lookup lands.
    press(tree, "Suggestion: Greek yogurt");
    press(tree, "Suggestion: Black coffee");
    await act(async () => {
      resolveLookup({ items: [yogurt], limit: 20 });
    });

    await act(async () => {
      press(tree, "Add entry");
    });

    // The stale hydration never attaches to the new text: the history chip's
    // submit takes the normal estimator path, no synthetic saved-food values.
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "black coffee",
      expect.any(String),
    );
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
    expect(textContent(tree)).not.toContain("200");
  });

  it("lets a typeahead selection supersede an in-flight chip hydration", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const yogurt = savedFood({ id: "sf-1", name: "Greek yogurt", calories: 200 });
    const oatmeal = savedFood({ id: "sf-2", name: "Oatmeal", calories: 350 });
    let resolveLookup!: (response: SavedFoodSearchResponse) => void;
    const searchSavedFoods = jest.fn().mockReturnValue(
      new Promise<SavedFoodSearchResponse>((resolve) => {
        resolveLookup = resolve;
      }),
    );
    let resolveCreate!: (dto: LogEventDTO) => void;
    const create = jest.fn().mockReturnValue(
      new Promise<LogEventDTO>((resolve) => {
        resolveCreate = resolve;
      }),
    );
    const getSuggestions = jest
      .fn()
      .mockResolvedValue({ items: [SAVED_SUGGESTION], limit: 8 });

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        searchSavedFoods={searchSavedFoods}
        getSuggestions={getSuggestions}
        useActive={ACTIVE}
      />,
    );
    await act(async () => {});

    // Chip tap starts the yogurt hydration; before it lands the user makes a
    // deliberate FTY-053 typeahead pick (driven through the bar's onSelect —
    // the debounce timer is irrelevant to what is being proven here).
    press(tree, "Suggestion: Greek yogurt");
    const typeahead = tree.root.findByType(TypeaheadSuggestionBar);
    act(() => {
      typeahead.props.onSelect(oatmeal);
    });
    await act(async () => {
      resolveLookup({ items: [yogurt], limit: 20 });
    });

    await act(async () => {
      press(tree, "Add entry");
    });

    // The explicit pick wins: the synthetic item carries Oatmeal's values and
    // the stale chip hydration never overwrote it.
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "Oatmeal",
      expect.any(String),
    );
    expect(textContent(tree)).toContain("350");
    expect(textContent(tree)).not.toContain("200");
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(false);

    await act(async () => {
      resolveCreate(
        event({ id: "server-6", raw_text: "Oatmeal", status: "pending" }),
      );
    });
    expect(textContent(tree)).toContain("350");
  });

  it("takes the normal estimator submit for a history-only chip (no saved_food_id)", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const searchSavedFoods = jest.fn();
    const create = jest
      .fn()
      .mockResolvedValue(
        event({ id: "server-2", raw_text: "black coffee", status: "pending" }),
      );
    const getSuggestions = jest
      .fn()
      .mockResolvedValue({ items: [HISTORY_SUGGESTION], limit: 8 });

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        searchSavedFoods={searchSavedFoods}
        getSuggestions={getSuggestions}
        useActive={ACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "Suggestion: Black coffee");
    });
    // A history-only chip never hits the saved-food lookup.
    expect(searchSavedFoods).not.toHaveBeenCalled();

    await act(async () => {
      press(tree, "Add entry");
    });
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "black coffee",
      expect.any(String),
    );
    // Normal estimator path: a pending skeleton, no synthetic value row.
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
  });

  it("refreshes the suggestions after a successful submit", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const create = jest
      .fn()
      .mockResolvedValue(
        event({ id: "server-3", raw_text: "black coffee", status: "pending" }),
      );
    const getSuggestions = jest
      .fn()
      .mockResolvedValue({ items: [HISTORY_SUGGESTION], limit: 8 });

    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        getSuggestions={getSuggestions}
        useActive={ACTIVE}
      />,
    );
    await act(async () => {});

    // One focus fetch so far.
    expect(getSuggestions).toHaveBeenCalledTimes(1);

    await act(async () => {
      press(tree, "Suggestion: Black coffee");
    });
    await act(async () => {
      press(tree, "Add entry");
    });

    // A successful submit re-reads the ranking (the just-logged item changes it).
    expect(getSuggestions).toHaveBeenCalledTimes(2);
  });
});
