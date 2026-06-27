import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { WeightScreen } from "./WeightScreen";
import { WeightApiError, type WeightEntryDTO } from "@/api/weightEntries";
import type { Session } from "@/state/session";

const SESSION: Session = {
  token: "test-token",
  userId: "22222222-2222-2222-2222-222222222222",
};

const NOW = new Date("2026-06-27T12:00:00Z");

function entry(overrides: Partial<WeightEntryDTO> = {}): WeightEntryDTO {
  return {
    id: "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
    user_id: SESSION!.userId,
    weight_kg: 70.0,
    effective_date: "2026-06-27",
    created_at: "2026-06-27T08:00:00Z",
    updated_at: "2026-06-27T08:00:00Z",
    ...overrides,
  };
}

function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 390, height: 844 },
          insets: { top: 47, left: 0, right: 0, bottom: 34 },
        }}
      >
        {element}
      </SafeAreaProvider>,
    );
  });
  return tree;
}

function textContent(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

function findInput(tree: ReactTestRenderer, label: string) {
  return tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onChangeText === "function",
  );
}

function pressButton(tree: ReactTestRenderer, label: string) {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
  act(() => {
    node.props.onPress();
  });
}

describe("WeightScreen — no session", () => {
  it("shows a sign-in message when no session is present", () => {
    const load = jest.fn();
    const tree = mount(
      <WeightScreen session={null} load={load} now={NOW} />,
    );
    expect(textContent(tree)).toContain("Sign in to log your weight");
    expect(load).not.toHaveBeenCalled();
  });
});

describe("WeightScreen — with session", () => {
  it("loads entries on mount and shows the trend chart section", async () => {
    const load = jest.fn().mockResolvedValue([entry()]);
    const tree = mount(
      <WeightScreen
        session={SESSION}
        load={load}
        create={jest.fn()}
        now={NOW}
      />,
    );
    expect(textContent(tree)).toContain("Weight");
    expect(textContent(tree)).toContain("Log weight");
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(1);
    const [, from, to] = load.mock.calls[0] as [unknown, string, string];
    expect(to).toBe("2026-06-27");
    expect(from).toBe("2026-03-29");
  });

  it("shows metric unit input for a metric user", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <WeightScreen
        session={SESSION}
        unitsPreference="metric"
        load={load}
        now={NOW}
      />,
    );
    await act(async () => {});
    expect(findInput(tree, "Weight in kg")).toBeTruthy();
  });

  it("shows imperial unit input for an imperial user", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <WeightScreen
        session={SESSION}
        unitsPreference="imperial"
        load={load}
        now={NOW}
      />,
    );
    await act(async () => {});
    expect(findInput(tree, "Weight in lb")).toBeTruthy();
  });

  it("shows the loading indicator while entries are fetching", () => {
    // Never-resolving load keeps the screen in loading state
    const load = jest.fn().mockReturnValue(new Promise(() => {}));
    const tree = mount(
      <WeightScreen session={SESSION} load={load} now={NOW} />,
    );
    const indicator = tree.root.find(
      (n) => n.props.accessibilityLabel === "Loading your weight trend",
    );
    expect(indicator).toBeTruthy();
  });

  it("shows a chart error and retry button when loading fails", async () => {
    const load = jest.fn().mockRejectedValue(
      new WeightApiError(500, "Could not load your weight log."),
    );
    const tree = mount(
      <WeightScreen session={SESSION} load={load} now={NOW} />,
    );
    await act(async () => {});
    expect(textContent(tree)).toContain("Could not load your weight log.");
    const retryBtn = tree.root.find(
      (n) => n.props.accessibilityLabel === "Try again",
    );
    expect(retryBtn).toBeTruthy();
  });

  it("shows an empty-state message when no entries exist", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <WeightScreen session={SESSION} load={load} now={NOW} />,
    );
    await act(async () => {});
    expect(textContent(tree)).toContain("No weight entries yet");
  });

  it("calls create with the entered weight and today's date on submit", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const create = jest.fn().mockResolvedValue(entry());
    const tree = mount(
      <WeightScreen
        session={SESSION}
        load={load}
        create={create}
        now={NOW}
      />,
    );
    await act(async () => {});

    act(() => {
      findInput(tree, "Weight in kg").props.onChangeText("71");
    });
    await act(async () => {
      pressButton(tree, "Log weight");
    });

    expect(create).toHaveBeenCalledTimes(1);
    const [, weight, date] = create.mock.calls[0] as [unknown, number, string];
    expect(weight).toBe(71);
    expect(date).toBe("2026-06-27");
  });

  it("re-fetches entries after a successful submission to show the new point", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const create = jest.fn().mockResolvedValue(entry());
    const tree = mount(
      <WeightScreen
        session={SESSION}
        load={load}
        create={create}
        now={NOW}
      />,
    );
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(1);

    act(() => {
      findInput(tree, "Weight in kg").props.onChangeText("71");
    });
    await act(async () => {
      pressButton(tree, "Log weight");
    });

    // load is called again after successful create
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("shows a submit error without echoing the weight value when create fails", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const create = jest.fn().mockRejectedValue(
      new WeightApiError(422, "That entry couldn't be saved. Check the value and try again."),
    );
    const tree = mount(
      <WeightScreen
        session={SESSION}
        load={load}
        create={create}
        now={NOW}
      />,
    );
    await act(async () => {});

    act(() => {
      findInput(tree, "Weight in kg").props.onChangeText("999999");
    });
    await act(async () => {
      pressButton(tree, "Log weight");
    });

    const content = textContent(tree);
    // Error message shown
    expect(content).toContain("couldn't be saved");
    // Weight value not echoed
    expect(content).not.toContain("999999");
  });
});
