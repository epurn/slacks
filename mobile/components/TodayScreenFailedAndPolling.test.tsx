import { act } from "react-test-renderer";

import { TodayScreen } from "./TodayScreen";
import {
  LogEventApiError,
  type LogEventDTO,
} from "@/api/logEvents";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

import {
  INACTIVE,
  SESSION,
  cleanupTrees,
  emptyClarification,
  event,
  foodItem,
  hasA11yLabel,
  inputValue,
  mount,
  press,
  sequentialKeys,
  textContent,
  typeInto,
} from "./today/todayTestUtils";

// The beat haptics are mocked so transitions can be asserted through the real
// screen without a native Taptic Engine, and so a resolve/save/target beat
// firing in these suites never reaches a real (unsupported) native call.
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

// The item-forward by-date feed (FTY-198) is read from a real endpoint by
// default (FTY-180). Stub it to an empty day so tests that don't exercise item
// rows stay hermetic — no real fetch — while tests that do pass an explicit
// `loadEntries` prop that overrides this default.
jest.mock("@/api/logEvents", () => {
  const actual = jest.requireActual("@/api/logEvents");
  return {
    ...actual,
    listTodayLogEventEntries: jest.fn().mockResolvedValue([]),
  };
});

beforeEach(() => mockReduceMotion(false));

afterEach(cleanupTrees);

describe("TodayScreen failed-parse rows (FTY-176)", () => {
  it("renders a failed parse as an actionable Retry + Edit-as-text row, never static", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "asdfghjkl", status: "failed" }),
      ]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    // Calm inline copy, the captured text, and a visibly-uncounted row.
    const content = textContent(tree);
    expect(content).toContain("asdfghjkl");
    expect(content).toContain("Couldn't read that");
    // The failed state is conveyed to VoiceOver via the status icon.
    expect(hasA11yLabel(tree, "Estimate didn't finish")).toBe(true);
    // Both affordances are present and tappable — not a static dead-end row.
    expect(hasA11yLabel(tree, "Retry")).toBe(true);
    expect(hasA11yLabel(tree, "Edit as text")).toBe(true);
  });

  it("Retry re-submits the same text with a NEW idempotency key and swaps in a pending row", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "asdfghjkl", status: "failed" }),
      ]);
    const create = jest
      .fn()
      .mockResolvedValue(
        event({ id: "server-2", raw_text: "asdfghjkl", status: "pending" }),
      );
    const keys = sequentialKeys();
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        generateKey={keys}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "Retry");
    });

    // A genuine new attempt via the create path — same text, a fresh key.
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "asdfghjkl",
      expect.any(String),
    );
    // The failed row is superseded in place by the new pending attempt — no
    // stale duplicate, and it is now a waiting-to-estimate skeleton row
    // (FTY-180), not the raw text.
    expect(hasA11yLabel(tree, "Retry")).toBe(false);
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
    expect(textContent(tree)).not.toContain("asdfghjkl");
  });

  it("Edit as text prefills the composer with the failed text and supersedes the row", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "asdfghjkl", status: "failed" }),
      ]);
    const create = jest
      .fn()
      .mockResolvedValue(
        event({ id: "server-2", raw_text: "an apple", status: "pending" }),
      );
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    act(() => {
      press(tree, "Edit as text");
    });

    // The failed text is now in the composer for the user to fix, and the row is
    // superseded in place (the text is safe in the composer, not lost).
    expect(inputValue(tree, "Log food or exercise")).toBe("asdfghjkl");
    expect(hasA11yLabel(tree, "Retry")).toBe(false);

    // Fixing the wording and submitting resubmits through the same create path.
    typeInto(tree, "Log food or exercise", "an apple");
    await act(async () => {
      press(tree, "Add entry");
    });
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "an apple",
      expect.any(String),
    );
  });

  it("a retry whose create call errors restores the actionable failed row and surfaces the error", async () => {
    jest.useFakeTimers();
    try {
      const load = jest
        .fn()
        .mockResolvedValue([
          event({ id: "a", raw_text: "asdfghjkl", status: "failed" }),
        ]);
      const create = jest
        .fn()
        .mockRejectedValue(
          new LogEventApiError(422, "That entry couldn't be saved."),
        );
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          create={create}
          useActive={INACTIVE}
        />,
      );
      await act(async () => {});

      await act(async () => {
        press(tree, "Retry");
      });

      // The create failed: the optimistic attempt is rolled back, the original
      // failed row reappears (still actionable), and the failure is surfaced.
      expect(hasA11yLabel(tree, "Retry")).toBe(true);
      expect(hasA11yLabel(tree, "Edit as text")).toBe(true);
      expect(textContent(tree)).toContain("That entry couldn't be saved.");
    } finally {
      jest.useRealTimers();
    }
  });

  it("keeps the retried failed row hidden even after a poll re-fetches it as failed", async () => {
    jest.useFakeTimers();
    try {
      const load = jest
        .fn()
        // Initial load + every poll keep returning the original failed row.
        .mockResolvedValue([
          event({ id: "a", raw_text: "asdfghjkl", status: "failed" }),
        ]);
      const create = jest
        .fn()
        .mockResolvedValue(
          event({ id: "server-2", raw_text: "asdfghjkl", status: "pending" }),
        );
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          create={create}
          useActive={() => true}
          pollIntervalMs={1000}
        />,
      );
      await act(async () => {});

      await act(async () => {
        press(tree, "Retry");
      });

      // The fresh attempt is pending → polling runs and re-fetches the original
      // failed row; it must stay superseded (retried this session).
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});

      expect(hasA11yLabel(tree, "Retry")).toBe(false);
    } finally {
      jest.useRealTimers();
    }
  });
});

describe("TodayScreen polling", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it("auto-refreshes a pending entry to its terminal status", async () => {
    const pending = event({ id: "a", raw_text: "Oatmeal", status: "pending" });
    const completed = event({ id: "a", raw_text: "Oatmeal", status: "completed" });
    const load = jest
      .fn()
      .mockResolvedValueOnce([pending])
      .mockResolvedValueOnce([completed]);
    const loadEntries = jest
      .fn()
      .mockResolvedValueOnce([{ event: pending, items: [] }])
      .mockResolvedValueOnce([{ event: completed, items: [] }]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        loadEntries={loadEntries}
        useActive={() => true}
        pollIntervalMs={1000}
      />,
    );
    await act(async () => {});
    // Pending: the shimmer skeleton, not the raw phrase.
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);

    // One interval later the screen polls, reaches the terminal status, and the
    // no-item completed response gets only a bounded resolve hold.
    act(() => jest.advanceTimersByTime(1000));
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(2);
    expect(hasA11yLabel(tree, "Estimating")).toBe(true);

    act(() => jest.advanceTimersByTime(200));
    await act(async () => {});
    expect(hasA11yLabel(tree, "Estimating")).toBe(false);
    expect(textContent(tree)).toContain("Oatmeal");
    expect(hasA11yLabel(tree, "Logged")).toBe(true);

    // Nothing is pending now, so polling stops — no further loads.
    act(() => jest.advanceTimersByTime(5000));
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("does not poll while the screen is inactive (backgrounded/unfocused)", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([event({ id: "a", status: "pending" })]);
    mount(
      <TodayScreen
        session={SESSION}
        load={load}
        useActive={() => false}
        pollIntervalMs={1000}
      />,
    );
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(1);

    act(() => jest.advanceTimersByTime(5000));
    await act(async () => {});
    expect(load).toHaveBeenCalledTimes(1);
  });

  it("keeps the timeline intact when a poll fails, then recovers", async () => {
    const load = jest
      .fn()
      .mockResolvedValueOnce([event({ id: "a", raw_text: "Oatmeal", status: "pending" })])
      .mockRejectedValueOnce(new LogEventApiError(500, "transient"))
      .mockResolvedValueOnce([event({ id: "a", raw_text: "Oatmeal", status: "completed" })]);
    // The by-date item feed carries the resolved value; it only surfaces once the
    // event-list poll recovers and reports `completed` (FTY-180).
    const loadEntries = jest.fn().mockResolvedValue([
      {
        event: event({ id: "a", raw_text: "Oatmeal", status: "completed" }),
        items: [foodItem({ name: "Oatmeal" })],
      },
    ]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        loadEntries={loadEntries}
        useActive={() => true}
        pollIntervalMs={1000}
      />,
    );
    await act(async () => {});
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);

    // A failed poll is swallowed; the pending entry is still shown.
    act(() => jest.advanceTimersByTime(1000));
    await act(async () => {});
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);

    // The next tick recovers, reconciles to the terminal status, and the value
    // resolves in place over the skeleton's footprint.
    act(() => jest.advanceTimersByTime(1000));
    await act(async () => {});
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(false);
    expect(hasA11yLabel(tree, "Oatmeal, 150 kcal")).toBe(true);
  });
});

describe("TodayScreen composer — calm, status-first", () => {
  it("does not auto-focus the composer on mount (Today is the status-home)", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    const input = tree.root.find(
      (n) => n.props.accessibilityLabel === "Log food or exercise",
    );
    // Auto-raising the keyboard on a dashboard is jarring (Calm by default).
    expect(input.props.autoFocus).toBeFalsy();
  });

  it("acknowledges a submit in the single timeline — no separate 'added this session' feed", async () => {
    const load = jest.fn().mockResolvedValue([]);
    let resolveCreate!: (dto: LogEventDTO) => void;
    const create = jest.fn().mockReturnValue(
      new Promise<LogEventDTO>((resolve) => {
        resolveCreate = resolve;
      }),
    );
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        getClarification={emptyClarification()}
        // The created entry's resolved value row comes from the item feed; seed it
        // so the completed entry resolves in place into its value (FTY-180).
        items={{ "server-1": [foodItem({ name: "greek yogurt" })] }}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "greek yogurt");
    press(tree, "Add entry");

    // Immediate acknowledgement in the canonical timeline; composer cleared.
    // The pending row is a skeleton (FTY-180), not the raw text — the
    // accessible status label is the acknowledgement.
    expect(textContent(tree)).not.toContain("greek yogurt");
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
    expect(inputValue(tree, "Log food or exercise")).toBe("");
    // There is exactly one timeline — no harvested "Added this session" feed.
    expect(textContent(tree)).not.toContain("Added this session");

    await act(async () => {
      resolveCreate(
        event({ id: "server-1", raw_text: "greek yogurt", status: "completed" }),
      );
    });
    // The completed entry surfaces as its resolved value row in the one timeline.
    expect(textContent(tree)).toContain("greek yogurt");
  });
});
