import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { TodayScreen } from "./TodayScreen";
import { LogEventApiError, type LogEventDTO } from "@/api/logEvents";
import type { Session } from "@/state/session";

const SESSION: Session = {
  token: "test-token",
  userId: "22222222-2222-2222-2222-222222222222",
};

function event(overrides: Partial<LogEventDTO>): LogEventDTO {
  return {
    id: "id",
    user_id: SESSION!.userId,
    raw_text: "two eggs and toast",
    status: "pending",
    created_at: "2026-06-26T08:00:00Z",
    updated_at: "2026-06-26T08:00:00Z",
    ...overrides,
  };
}

// SafeAreaProvider needs frame/insets metrics in a non-native test environment.
function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(
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

function hasA11yLabel(tree: ReactTestRenderer, label: string): boolean {
  return tree.root.findAll((n) => n.props.accessibilityLabel === label).length > 0;
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

describe("TodayScreen", () => {
  it("prompts sign-in when there is no session", () => {
    const tree = mount(<TodayScreen session={null} />);
    expect(textContent(tree)).toContain("Sign in to see your day");
  });

  it("loads and renders the day's events with accessible status", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "Oatmeal", status: "completed" }),
        event({ id: "b", raw_text: "Cold brew", status: "pending" }),
      ]);
    const tree = mount(<TodayScreen session={SESSION} load={load} />);
    await act(async () => {});

    expect(load).toHaveBeenCalledTimes(1);
    const content = textContent(tree);
    expect(content).toContain("Oatmeal");
    expect(content).toContain("Cold brew");
    // Pending and completed are distinguished by accessible status labels.
    expect(hasA11yLabel(tree, "Logged")).toBe(true);
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
  });

  it("shows a nonjudgmental empty state when there are no events", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(<TodayScreen session={SESSION} load={load} />);
    await act(async () => {});

    expect(textContent(tree)).toContain("Nothing logged yet");
  });

  it("surfaces a load error with a retry affordance", async () => {
    const load = jest
      .fn()
      .mockRejectedValueOnce(new LogEventApiError(401, "Your session has expired."))
      .mockResolvedValueOnce([event({ id: "a", raw_text: "Oatmeal", status: "pending" })]);
    const tree = mount(<TodayScreen session={SESSION} load={load} />);
    await act(async () => {});

    expect(textContent(tree)).toContain("Your session has expired.");
    expect(hasA11yLabel(tree, "Try again")).toBe(true);

    // Retrying re-fetches and renders the recovered day.
    press(tree, "Try again");
    await act(async () => {});
    expect(textContent(tree)).toContain("Oatmeal");
  });

  it("shows a submitted entry immediately as pending, then reconciles", async () => {
    const load = jest.fn().mockResolvedValue([]);
    let resolveCreate!: (dto: LogEventDTO) => void;
    const create = jest.fn().mockReturnValue(
      new Promise<LogEventDTO>((resolve) => {
        resolveCreate = resolve;
      }),
    );
    const tree = mount(
      <TodayScreen session={SESSION} load={load} create={create} />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "  greek yogurt  ");
    press(tree, "Add entry");

    // Optimistic: the entry appears as pending before the create resolves.
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "greek yogurt",
    );
    expect(textContent(tree)).toContain("greek yogurt");
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);

    await act(async () => {
      resolveCreate(
        event({ id: "server-1", raw_text: "greek yogurt", status: "pending" }),
      );
    });
    expect(textContent(tree)).toContain("greek yogurt");
  });

  it("rolls back and restores input when create fails", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const create = jest
      .fn()
      .mockRejectedValue(new LogEventApiError(422, "That entry couldn't be saved."));
    const tree = mount(
      <TodayScreen session={SESSION} load={load} create={create} />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "blernsday");
    await act(async () => {
      press(tree, "Add entry");
    });

    expect(textContent(tree)).toContain("That entry couldn't be saved.");
    // Optimistic entry rolled back to the empty state.
    expect(textContent(tree)).toContain("Nothing logged yet");
  });
});
