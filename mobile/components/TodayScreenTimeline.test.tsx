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
  countPendingRows,
  emptyClarification,
  event,
  foodItem,
  hasA11yLabel,
  mount,
  press,
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

describe("TodayScreen", () => {
  it("prompts sign-in when there is no session", () => {
    const tree = mount(<TodayScreen session={null} useActive={INACTIVE} />);
    expect(textContent(tree)).toContain("Sign in to see your day");
  });

  it("loads and renders the day's events with accessible status", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "Oatmeal", status: "completed" }),
        event({ id: "b", raw_text: "Cold brew", status: "pending" }),
      ]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    expect(load).toHaveBeenCalledTimes(1);
    const content = textContent(tree);
    expect(content).toContain("Oatmeal");
    // The pending entry renders a skeleton, not its raw text (FTY-180) — the
    // "thinking" state fills in place with no literal "Waiting"/"thinking" copy.
    expect(content).not.toContain("Cold brew");
    // Pending and completed are distinguished by accessible status labels.
    expect(hasA11yLabel(tree, "Logged")).toBe(true);
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
  });

  it("shows a calm empty state invite when there are no events", async () => {
    const load = jest.fn().mockResolvedValue([]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    expect(textContent(tree)).toContain("Log your first thing");
  });

  it("surfaces a load error with a retry affordance", async () => {
    const load = jest
      .fn()
      .mockRejectedValueOnce(new LogEventApiError(401, "Your session has expired."))
      .mockResolvedValueOnce([event({ id: "a", raw_text: "Oatmeal", status: "pending" })]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    expect(textContent(tree)).toContain("Your session has expired.");
    expect(hasA11yLabel(tree, "Try again")).toBe(true);

    // Retrying re-fetches and renders the recovered day. The recovered entry is
    // pending, so it renders as a skeleton (FTY-180) rather than its raw text —
    // the accessible status label is the proof the day reloaded.
    press(tree, "Try again");
    await act(async () => {});
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
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
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        getClarification={emptyClarification()}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    typeInto(tree, "Log food or exercise", "  greek yogurt  ");
    press(tree, "Add entry");

    // Optimistic: the entry appears as pending before the create resolves.
    // create carries the FTY-096 idempotency key minted by the submit machine.
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "greek yogurt",
      expect.any(String),
    );
    // A pending entry renders as a skeleton, not its raw text (FTY-180) — the
    // accessible status label is the acknowledgement that the row landed.
    expect(textContent(tree)).not.toContain("greek yogurt");
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
    const pendingRowsBeforeReconcile = countPendingRows(tree, "Waiting to estimate");

    await act(async () => {
      resolveCreate(
        event({ id: "server-1", raw_text: "greek yogurt", status: "pending" }),
      );
    });
    // Reconciled to the server event in place — still the same single pending
    // row, no duplicate spawned by the swap.
    expect(countPendingRows(tree, "Waiting to estimate")).toBe(
      pendingRowsBeforeReconcile,
    );
  });

  it("rolls back and restores input when create fails", async () => {
    // Fake timers prevent the restored text from leaking a dangling debounce
    // timer that would fire after Jest tears down the test.
    jest.useFakeTimers();
    try {
      const load = jest.fn().mockResolvedValue([]);
      const create = jest
        .fn()
        .mockRejectedValue(new LogEventApiError(422, "That entry couldn't be saved."));
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          create={create}
          useActive={INACTIVE}
        />,
      );
      await act(async () => {});

      typeInto(tree, "Log food or exercise", "blernsday");
      await act(async () => {
        press(tree, "Add entry");
      });

      expect(textContent(tree)).toContain("That entry couldn't be saved.");
      // Optimistic entry rolled back to the empty state.
      expect(textContent(tree)).toContain("Log your first thing");
    } finally {
      jest.useRealTimers();
    }
  });
});

describe("TodayScreen derived items", () => {
  it("renders item rows (name · kcal) for a completed event with derived items", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([event({ id: "a", raw_text: "Greek yogurt", status: "completed" })]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        items={{ a: [foodItem()] }}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // The new design shows item rows (name · kcal · source icon) for completed events
    expect(textContent(tree)).toContain("Greek yogurt");
    expect(textContent(tree)).toContain("150 kcal");
  });

  it("shows a skeleton, not raw text, for a pending event without derived items yet", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([event({ id: "b", raw_text: "Cold brew", status: "pending" })]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        items={{}}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // Pending events without items render the "thinking" skeleton sized to the
    // resolved row (FTY-180) — never the raw phrase or literal "Waiting" text.
    expect(textContent(tree)).not.toContain("Cold brew");
    expect(textContent(tree)).not.toContain("Waiting");
    expect(hasA11yLabel(tree, "Waiting to estimate")).toBe(true);
    expect(
      tree.root.findAll((n) => n.props.accessibilityRole === "progressbar")
        .length,
    ).toBeGreaterThan(0);
  });
});

describe("TodayScreen timeline timestamps (FTY-174 / audit A6)", () => {
  it("renders a known morning entry with the correct AM meridiem, never PM", async () => {
    // The exact regression: an 11:14 AM local instant must show "11:14 AM" in the
    // real timeline cluster header — not "11:14 PM" (the observed Hermes bug).
    //
    // Build the instant from *local* wall-clock components (11:14 on the machine's
    // own zone) so the assertion is deterministic on any CI timezone: the header
    // renders in the device zone, so it must read back the same 11:14 AM. The
    // stored `created_at` is that instant serialized to UTC, exactly as the
    // tz-aware backend (FTY-173) would send it.
    const localMorning = new Date(2026, 5, 27, 11, 14, 0); // 11:14 AM, device zone
    const load = jest.fn().mockResolvedValue([
      event({
        id: "morning",
        raw_text: "Oatmeal",
        status: "completed",
        created_at: localMorning.toISOString(),
      }),
    ]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    const content = textContent(tree);
    expect(content).toContain("Oatmeal");
    expect(content).toContain("11:14 AM");
    expect(content).not.toContain("11:14 PM");
  });
});
