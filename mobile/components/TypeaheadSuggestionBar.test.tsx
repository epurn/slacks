import { act, create as render, type ReactTestRenderer } from "react-test-renderer";

import { TypeaheadSuggestionBar } from "./TypeaheadSuggestionBar";
import { CHIP_HIT_SLOP } from "@/components/ui";
import type { SavedFoodDTO, SavedFoodSession } from "@/api/savedFoods";

const SESSION: SavedFoodSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "11111111-1111-1111-1111-111111111111",
};

function savedFood(overrides: Partial<SavedFoodDTO> = {}): SavedFoodDTO {
  return {
    id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
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

describe("TypeaheadSuggestionBar – empty/no-match state", () => {
  it("renders nothing when query is empty", () => {
    const search = jest.fn();
    const tree = mount(
      <TypeaheadSuggestionBar query="" session={SESSION} onSelect={jest.fn()} search={search} />,
    );
    expect(tree.toJSON()).toBeNull();
    expect(search).not.toHaveBeenCalled();
  });

  it("renders nothing when query is whitespace only", () => {
    const search = jest.fn();
    const tree = mount(
      <TypeaheadSuggestionBar query="   " session={SESSION} onSelect={jest.fn()} search={search} />,
    );
    expect(tree.toJSON()).toBeNull();
    expect(search).not.toHaveBeenCalled();
  });

  it("renders nothing when there is no session", () => {
    const search = jest.fn();
    const tree = mount(
      <TypeaheadSuggestionBar query="greek" session={null} onSelect={jest.fn()} search={search} />,
    );
    expect(tree.toJSON()).toBeNull();
    expect(search).not.toHaveBeenCalled();
  });

  it("renders nothing when the search returns no matches", async () => {
    jest.useFakeTimers();
    const search = jest.fn().mockResolvedValue({ items: [], limit: 20 });
    const tree = mount(
      <TypeaheadSuggestionBar query="zzz" session={SESSION} onSelect={jest.fn()} search={search} />,
    );
    // Advance timers past debounce so the search fires.
    await act(async () => {
      jest.advanceTimersByTime(400);
    });
    expect(tree.toJSON()).toBeNull();
    jest.useRealTimers();
  });

  it("renders nothing when the search errors (silently fails)", async () => {
    jest.useFakeTimers();
    const search = jest.fn().mockRejectedValue(new Error("network error"));
    const tree = mount(
      <TypeaheadSuggestionBar query="greek" session={SESSION} onSelect={jest.fn()} search={search} />,
    );
    await act(async () => {
      jest.advanceTimersByTime(400);
    });
    expect(tree.toJSON()).toBeNull();
    jest.useRealTimers();
  });
});

describe("TypeaheadSuggestionBar – debounce behavior", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("does not call search before the debounce window", () => {
    const search = jest.fn().mockResolvedValue({ items: [savedFood()], limit: 20 });
    mount(
      <TypeaheadSuggestionBar query="greek" session={SESSION} onSelect={jest.fn()} search={search} />,
    );
    // No search before 300ms.
    act(() => jest.advanceTimersByTime(200));
    expect(search).not.toHaveBeenCalled();
  });

  it("calls search with the trimmed query after the debounce window", async () => {
    const search = jest.fn().mockResolvedValue({ items: [savedFood()], limit: 20 });
    mount(
      <TypeaheadSuggestionBar query="  greek  " session={SESSION} onSelect={jest.fn()} search={search} />,
    );
    await act(async () => {
      jest.advanceTimersByTime(400);
    });
    expect(search).toHaveBeenCalledTimes(1);
    expect(search).toHaveBeenCalledWith(SESSION, "greek");
  });

  it("cancels the pending search when query changes before debounce fires", async () => {
    const search = jest.fn().mockResolvedValue({ items: [savedFood()], limit: 20 });
    let tree!: ReactTestRenderer;
    act(() => {
      tree = render(
        <TypeaheadSuggestionBar query="g" session={SESSION} onSelect={jest.fn()} search={search} />,
      );
    });

    // Type "gr" before the 300ms window.
    act(() => {
      jest.advanceTimersByTime(100);
      tree.update(
        <TypeaheadSuggestionBar query="gr" session={SESSION} onSelect={jest.fn()} search={search} />,
      );
    });

    // First timer was cancelled; only one call should fire after 300ms more.
    // Use async act so the resolved search promise's then() drains before the
    // test ends (avoids "update not wrapped in act" console.error).
    await act(async () => { jest.advanceTimersByTime(400); });
    expect(search).toHaveBeenCalledTimes(1);
    expect(search).toHaveBeenCalledWith(SESSION, "gr");
  });
});

describe("TypeaheadSuggestionBar – rendering matches", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("renders each matched saved food as an accessible suggestion chip", async () => {
    const foods = [
      savedFood({ id: "a", name: "Greek yogurt" }),
      savedFood({ id: "b", name: "Greek salad" }),
    ];
    const search = jest.fn().mockResolvedValue({ items: foods, limit: 20 });

    const tree = mount(
      <TypeaheadSuggestionBar query="greek" session={SESSION} onSelect={jest.fn()} search={search} />,
    );
    await act(async () => {
      jest.advanceTimersByTime(400);
    });

    expect(textContent(tree)).toContain("Greek yogurt");
    expect(textContent(tree)).toContain("Greek salad");
    expect(hasA11yLabel(tree, "Use saved food: Greek yogurt")).toBe(true);
    expect(hasA11yLabel(tree, "Use saved food: Greek salad")).toBe(true);
  });

  it("clears suggestions when the query is cleared", async () => {
    const food = savedFood({ name: "Greek yogurt" });
    const search = jest.fn().mockResolvedValue({ items: [food], limit: 20 });

    let tree!: ReactTestRenderer;
    act(() => {
      tree = render(
        <TypeaheadSuggestionBar query="greek" session={SESSION} onSelect={jest.fn()} search={search} />,
      );
    });
    await act(async () => {
      jest.advanceTimersByTime(400);
    });
    expect(textContent(tree)).toContain("Greek yogurt");

    // Clear the query.
    act(() => {
      tree.update(
        <TypeaheadSuggestionBar query="" session={SESSION} onSelect={jest.fn()} search={search} />,
      );
    });
    expect(tree.toJSON()).toBeNull();
  });
});

describe("TypeaheadSuggestionBar – shared chip style + hit target (FTY-193)", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("renders each chip with the shared Chip primitive's hitSlop, giving a >=44pt effective touch target", async () => {
    const foods = [savedFood({ id: "a", name: "Greek yogurt" })];
    const search = jest.fn().mockResolvedValue({ items: foods, limit: 20 });

    const tree = mount(
      <TypeaheadSuggestionBar query="greek" session={SESSION} onSelect={jest.fn()} search={search} />,
    );
    await act(async () => {
      jest.advanceTimersByTime(400);
    });

    const chip = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Use saved food: Greek yogurt" &&
        n.props.accessibilityRole === "button",
    );
    expect(chip.props.hitSlop).toEqual(CHIP_HIT_SLOP);

    const flatStyle: Array<Record<string, unknown>> = Array.isArray(chip.props.style)
      ? chip.props.style
      : [chip.props.style];
    const combined = Object.assign({}, ...flatStyle);
    expect(typeof combined.minHeight).toBe("number");
    expect((combined.minHeight as number) + CHIP_HIT_SLOP.top + CHIP_HIT_SLOP.bottom).toBeGreaterThanOrEqual(44);
  });

  it("still fires onSelect on tap once the shared chip is adopted", async () => {
    const food = savedFood({ id: "a", name: "Greek yogurt" });
    const search = jest.fn().mockResolvedValue({ items: [food], limit: 20 });
    const onSelect = jest.fn();

    const tree = mount(
      <TypeaheadSuggestionBar query="greek" session={SESSION} onSelect={onSelect} search={search} />,
    );
    await act(async () => {
      jest.advanceTimersByTime(400);
    });

    press(tree, "Use saved food: Greek yogurt");

    expect(onSelect).toHaveBeenCalledWith(food);
  });
});

describe("TypeaheadSuggestionBar – apply on tap", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("calls onSelect with the tapped saved food", async () => {
    const food = savedFood({ id: "a", name: "Greek yogurt" });
    const search = jest.fn().mockResolvedValue({ items: [food], limit: 20 });
    const onSelect = jest.fn();

    const tree = mount(
      <TypeaheadSuggestionBar query="greek" session={SESSION} onSelect={onSelect} search={search} />,
    );
    await act(async () => {
      jest.advanceTimersByTime(400);
    });

    press(tree, "Use saved food: Greek yogurt");

    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(food);
  });

  it("calls onSelect with the exact saved food carrying its stored nutrition", async () => {
    const food = savedFood({
      id: "b",
      name: "Oatmeal",
      calories: 300,
      protein_g: 10,
      carbs_g: 54,
      fat_g: 5,
      serving_size: 1,
      serving_unit: "bowl",
    });
    const search = jest.fn().mockResolvedValue({ items: [food], limit: 20 });
    const onSelect = jest.fn();

    const tree = mount(
      <TypeaheadSuggestionBar query="oat" session={SESSION} onSelect={onSelect} search={search} />,
    );
    await act(async () => {
      jest.advanceTimersByTime(400);
    });

    press(tree, "Use saved food: Oatmeal");

    expect(onSelect).toHaveBeenCalledWith(
      expect.objectContaining({
        id: "b",
        name: "Oatmeal",
        calories: 300,
        protein_g: 10,
      }),
    );
  });
});
