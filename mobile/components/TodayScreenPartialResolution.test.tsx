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
  summary,
  textContent,
} from "./today/todayTestUtils";

// Beat haptics are mocked so transitions can be asserted through the real screen
// without a native Taptic Engine.
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

// A mixed log: "greek yogurt and some hummus" resolves the yogurt (counted) and
// leaves the hummus as one open item-scoped question.
const PARTIAL_EVENT = event({
  id: "a",
  raw_text: "greek yogurt and some hummus",
  status: "partially_resolved",
});

const RESOLVED_SIBLING = foodItem({
  id: "item-yogurt",
  log_event_id: "a",
  name: "Greek yogurt",
  calories: 150,
  status: "resolved",
});

/** One open item-scoped question — its text names the component, not the phrase. */
function hummusQuestion(options: readonly string[] = ["2 tbsp", "1/4 cup"]) {
  return jest.fn().mockResolvedValue({
    questions: [{ id: "q1", text: "How much hummus?", options }],
  });
}

describe("TodayScreen partially-resolved entries (FTY-330)", () => {
  it("renders resolved siblings as counted rows plus one item-named pending-question row", async () => {
    const load = jest.fn().mockResolvedValue([PARTIAL_EVENT]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        items={{ a: [RESOLVED_SIBLING] }}
        getClarification={hummusQuestion()}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    const content = textContent(tree);
    // The resolved sibling is a normal counted row (name · kcal).
    expect(content).toContain("Greek yogurt");
    expect(content).toContain("150 kcal");
    // The open component renders one pending-question row from the question text.
    expect(content).toContain("How much hummus?");
    // The raw diary phrase is never surfaced as a row on a partial event — the
    // component is named by the question, honouring the privacy rule.
    expect(content).not.toContain("greek yogurt and some hummus");

    // The pending-question row is item-named, visibly uncounted, and tappable.
    const row = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "How much hummus?, needs a detail, uncounted" &&
        typeof n.props.onPress === "function",
    );
    expect(row.props.accessibilityRole).toBe("button");
  });

  it("renders one pending-question row per open component", async () => {
    const load = jest.fn().mockResolvedValue([PARTIAL_EVENT]);
    const twoQuestions = jest.fn().mockResolvedValue({
      questions: [
        { id: "q1", text: "How much hummus?", options: [] },
        { id: "q2", text: "How much olive oil?", options: [] },
      ],
    });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        items={{ a: [RESOLVED_SIBLING] }}
        getClarification={twoQuestions}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    expect(hasA11yLabel(tree, "How much hummus?, needs a detail, uncounted")).toBe(true);
    expect(hasA11yLabel(tree, "How much olive oil?, needs a detail, uncounted")).toBe(true);
  });

  it("opens the clarify sheet pre-targeted to the tapped component's own question", async () => {
    const load = jest.fn().mockResolvedValue([PARTIAL_EVENT]);
    const getClarification = hummusQuestion();
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        items={{ a: [RESOLVED_SIBLING] }}
        getClarification={getClarification}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // The sheet is not mounted until the row is tapped.
    expect(hasA11yLabel(tree, "Your answer")).toBe(false);

    await act(async () => {
      press(tree, "How much hummus?, needs a detail, uncounted");
    });

    // The sheet shows that exact question + its quick-pick chips immediately —
    // the timeline already holds the item-scoped question, so no re-fetch is
    // needed to name the component (never the generic fallback prompt).
    expect(textContent(tree)).toContain("How much hummus?");
    expect(textContent(tree)).not.toContain("We need a detail");
    expect(hasA11yLabel(tree, "2 tbsp")).toBe(true);
    expect(hasA11yLabel(tree, "Your answer")).toBe(true);
  });

  it("resolves the open component in place: the answer targets its question id and the sibling row is untouched", async () => {
    const load = jest.fn().mockResolvedValue([PARTIAL_EVENT]);
    const create = jest.fn();
    // The answer round-trip returns the SAME event, now processing (a scoped
    // re-estimate of just the answered component).
    const answerClarification = jest
      .fn()
      .mockResolvedValue(event({ id: "a", raw_text: PARTIAL_EVENT.raw_text, status: "processing" }));
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        items={{ a: [RESOLVED_SIBLING] }}
        getClarification={hummusQuestion()}
        answerClarification={answerClarification}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "How much hummus?, needs a detail, uncounted");
    });
    // Tap the "2 tbsp" quick-pick chip.
    await act(async () => {
      press(tree, "2 tbsp");
    });

    // The answer travels the first-class round-trip keyed on the event + the
    // component's own question id — never the create path.
    expect(answerClarification).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "a",
      "q1",
      "2 tbsp",
    );
    expect(create).not.toHaveBeenCalled();

    // The event flips to a scoped re-estimate (processing): the open component's
    // row is gone (it resolves in place), while the already-counted sibling stays
    // exactly as it was — no change, no duplicate.
    expect(hasA11yLabel(tree, "How much hummus?, needs a detail, uncounted")).toBe(false);
    const content = textContent(tree);
    expect(content).toContain("Greek yogurt");
    expect(content).toContain("150 kcal");
  });

  it("completes the entry in place once the re-estimate resolves the last component", async () => {
    jest.useFakeTimers();
    try {
      const processing = event({ id: "a", raw_text: PARTIAL_EVENT.raw_text, status: "processing" });
      const completed = event({ id: "a", raw_text: PARTIAL_EVENT.raw_text, status: "completed" });
      // After the answer advances it server-side, polling returns processing then
      // the completed event with the full costed set on the by-date feed.
      const load = jest
        .fn()
        .mockResolvedValueOnce([PARTIAL_EVENT])
        .mockResolvedValue([completed]);
      const hummus = foodItem({
        id: "item-hummus",
        log_event_id: "a",
        name: "Hummus",
        calories: 70,
        status: "resolved",
      });
      const loadEntries = jest
        .fn()
        .mockResolvedValueOnce([{ event: PARTIAL_EVENT, items: [RESOLVED_SIBLING] }])
        .mockResolvedValue([{ event: completed, items: [RESOLVED_SIBLING, hummus] }]);
      const answerClarification = jest.fn().mockResolvedValue(processing);
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          loadEntries={loadEntries}
          getClarification={hummusQuestion()}
          answerClarification={answerClarification}
          getDailySummary={jest.fn().mockResolvedValue(summary())}
          useActive={() => true}
          pollIntervalMs={1000}
        />,
      );
      await act(async () => {});

      await act(async () => {
        press(tree, "How much hummus?, needs a detail, uncounted");
      });
      await act(async () => {
        press(tree, "2 tbsp");
      });

      // Poll drives the re-estimate to completion; the entry resolves in place
      // to the full costed set, now a two-item meal that collapses to one row
      // (FTY-420) — the meal label (raw-phrase fallback) and the summed total
      // (150 + 70 = 220 kcal) — and the open-question row never reappears.
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});

      const content = textContent(tree);
      expect(content).toContain("220 kcal");
      expect(
        hasA11yLabel(tree, "greek yogurt and some hummus, 220 kcal total, 2 items"),
      ).toBe(true);
      expect(hasA11yLabel(tree, "How much hummus?, needs a detail, uncounted")).toBe(false);
    } finally {
      jest.useRealTimers();
    }
  });

  it("reflects the daily-summary semantics in the hero: the resolved sibling counts immediately", async () => {
    const load = jest.fn().mockResolvedValue([PARTIAL_EVENT]);
    // The backend already counts the resolved sibling in intake and reports the
    // open component under uncounted_entries; the client just renders the summary.
    const getDailySummary = jest.fn().mockResolvedValue(
      summary({
        intake: { calories: 150, protein_g: 20, carbs_g: 8, fat_g: 4 },
        uncounted_entries: 1,
      }),
    );
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        items={{ a: [RESOLVED_SIBLING] }}
        getClarification={hummusQuestion()}
        getDailySummary={getDailySummary}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // The hero shows the counted sibling's calories (150 of the 2000 target).
    expect(hasA11yLabel(tree, "150 of 2,000 kcal, 8 percent, 1,850 remaining")).toBe(true);
  });

  it("leaves a whole-event needs_clarification entry rendering exactly as before", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([event({ id: "b", raw_text: "milk", status: "needs_clarification" })]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getClarification={jest.fn().mockResolvedValue({ questions: [] })}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // The event-level case is unchanged: the raw phrase is the row's text and the
    // "Add a detail" affordance is shown (never the item-scoped question mapping).
    const content = textContent(tree);
    expect(content).toContain("milk");
    expect(content).toContain("Add a detail");
    expect(hasA11yLabel(tree, "milk, needs a detail, uncounted")).toBe(true);
  });
});
