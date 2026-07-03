import { act } from "react-test-renderer";

import { TodayScreen } from "./TodayScreen";
import {
  LogEventApiError,
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

// ─── Correction / detail sheet wiring (FTY-148) ──────────────────────────────

/** Resolve the style object for a node, collapsing a Pressable style function. */
function resolvedStyle(node: { props: { style?: unknown } }): Record<string, unknown> {
  const raw =
    typeof node.props.style === "function"
      ? (node.props.style as (s: { pressed: boolean }) => unknown)({ pressed: false })
      : node.props.style;
  return Object.assign(
    {},
    ...([] as unknown[]).concat(raw).filter(Boolean) as Record<string, unknown>[],
  );
}

describe("TodayScreen correction sheet wiring", () => {
  it("opens the correction sheet for a tapped completed item; the sheet is not mounted until then", async () => {
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

    // Dead until wired: the sheet (and its stepper) is not in the tree yet.
    expect(hasA11yLabel(tree, "Increase amount")).toBe(false);

    // Tapping the completed item row opens the sheet (mounted, reachable).
    press(tree, "Greek yogurt, 150 kcal");
    expect(hasA11yLabel(tree, "Increase amount")).toBe(true);
    expect(hasA11yLabel(tree, "Decrease amount")).toBe(true);
  });

  it("opens the sheet for the specific item that was tapped", async () => {
    const editItem = jest.fn().mockResolvedValue(foodItem({ id: "item-b" }));
    const load = jest
      .fn()
      .mockResolvedValue([event({ id: "a", raw_text: "Two snacks", status: "completed" })]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        editItem={editItem}
        items={{
          a: [
            foodItem({ id: "item-a", name: "Apple", calories: 95 }),
            foodItem({ id: "item-b", name: "Banana", calories: 105 }),
          ],
        }}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // Tap the second row, then exercise a lever; the edit targets that item's id.
    press(tree, "Banana, 105 kcal");
    await act(async () => {
      press(tree, "Increase amount");
    });

    expect(editItem).toHaveBeenCalledTimes(1);
    const [, itemType, itemId] = editItem.mock.calls[0];
    expect(itemType).toBe("food");
    expect(itemId).toBe("item-b");
  });

  it("drives the portion stepper end-to-end and reflects the recomputed item on close", async () => {
    // The server recomputes calories for the new portion; the UI re-renders the
    // returned values (never client math) and the timeline reflects them on close.
    const editItem = jest
      .fn()
      .mockResolvedValue(foodItem({ amount: 1.25, calories: 188 }));
    const load = jest
      .fn()
      .mockResolvedValue([event({ id: "a", raw_text: "Greek yogurt", status: "completed" })]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        editItem={editItem}
        items={{ a: [foodItem()] }}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    press(tree, "Greek yogurt, 150 kcal");
    await act(async () => {
      press(tree, "Increase amount");
    });

    // FTY-092 amount-adjust called with the stepped quantity; server values shown.
    expect(editItem).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "food",
      "item-1",
      "quantity",
      1.25,
    );
    expect(textContent(tree)).toContain("188");

    // Closing returns to the timeline, which now reflects the recomputed value.
    press(tree, "Close");
    expect(hasA11yLabel(tree, "Increase amount")).toBe(false);
    expect(hasA11yLabel(tree, "Greek yogurt, 188 kcal")).toBe(true);
  });

  it("exposes a ≥44pt tap target with a VoiceOver label on the completed item row", async () => {
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

    const row = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Greek yogurt, 150 kcal" &&
        typeof n.props.onPress === "function",
    );
    expect(row.props.accessibilityRole).toBe("button");
    expect(row.props.accessibilityHint).toBe("Tap to view details");
    expect(resolvedStyle(row).minHeight).toBeGreaterThanOrEqual(44);
  });
});

describe("TodayScreen needs-clarification entries", () => {
  it("renders a needs_clarification entry legibly and invitingly, never a silent row", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    const text = textContent(tree);
    expect(text).toContain("Add a detail");
    expect(text).toContain("milk");
  });

  it("exposes the needs-a-detail state and a resolve hint to VoiceOver on a ≥44pt target", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const tree = mount(
      <TodayScreen session={SESSION} load={load} useActive={INACTIVE} />,
    );
    await act(async () => {});

    const row = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "milk, needs a detail, uncounted" &&
        typeof n.props.onPress === "function",
    );
    expect(row.props.accessibilityRole).toBe("button");
    expect(row.props.accessibilityHint).toBe(
      "Tap to see the full phrase and add the missing detail",
    );
    expect(resolvedStyle(row).minHeight).toBeGreaterThanOrEqual(44);
  });

  it("opens the correction sheet in clarify-mode on tap, with no auto-filled detail", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getClarification={emptyClarification()}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    // The clarify free-text input is not mounted until the row is tapped.
    expect(hasA11yLabel(tree, "Your answer")).toBe(false);

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });

    // Clarify-mode is shown: free-text fallback present, and the missing detail
    // is never pre-filled (Fatty does not fabricate the answer).
    expect(hasA11yLabel(tree, "Your answer")).toBe(true);
    expect(inputValue(tree, "Your answer")).toBe("");
    // Clarify-mode only — the amount stepper / change-match levers stay hidden.
    expect(hasA11yLabel(tree, "Increase amount")).toBe(false);
  });

  it("resolves via the answer round-trip so the SAME entry recomputes in place — no create, no duplicate", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const create = jest.fn();
    // The round-trip returns the SAME event (id "a"), transitioned to processing,
    // with its raw phrase untouched — the backend re-estimates it in place.
    const answerClarification = jest
      .fn()
      .mockResolvedValue(
        event({ id: "a", raw_text: "milk", status: "processing" }),
      );
    const getClarification = jest.fn().mockResolvedValue({
      questions: [
        { id: "q1", text: "What kind of milk?", options: ["Whole", "2%", "Skim"] },
      ],
    });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        create={create}
        answerClarification={answerClarification}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });
    // Tap the "2%" quick-pick chip → one tap resolves via the answer round-trip.
    await act(async () => {
      press(tree, "2%");
    });

    // The answer travels the first-class round-trip keyed on the event + question
    // id — never the create path — so no second event is spawned and the raw
    // phrase is never mutated (audit A3/A5).
    expect(answerClarification).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "a",
      "q1",
      "2%",
    );
    expect(create).not.toHaveBeenCalled();

    // The same entry transitions in place (→ processing): its needs-a-detail
    // treatment is gone, and no duplicate "milk" row stands in for it.
    expect(hasA11yLabel(tree, "milk, needs a detail, uncounted")).toBe(false);
  });

  it("resolves a free-text answer via the round-trip when options are absent", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const answerClarification = jest
      .fn()
      .mockResolvedValue(
        event({ id: "a", raw_text: "milk", status: "processing" }),
      );
    // A deterministic backend-raised question carries no options — free text only.
    const getClarification = jest.fn().mockResolvedValue({
      questions: [{ id: "q1", text: "What kind of milk?", options: [] }],
    });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        answerClarification={answerClarification}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });
    typeInto(tree, "Your answer", "Oat milk");
    await act(async () => {
      press(tree, "Submit answer");
    });

    expect(answerClarification).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "a",
      "q1",
      "Oat milk",
    );
    expect(hasA11yLabel(tree, "milk, needs a detail, uncounted")).toBe(false);
  });

  it("surfaces an error and keeps the entry actionable when the answer round-trip fails", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const answerClarification = jest
      .fn()
      .mockRejectedValue(
        new LogEventApiError(422, "That entry couldn't be saved."),
      );
    const getClarification = jest.fn().mockResolvedValue({
      questions: [
        { id: "q1", text: "What kind of milk?", options: ["Whole", "2%", "Skim"] },
      ],
    });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        answerClarification={answerClarification}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });
    await act(async () => {
      press(tree, "2%");
    });

    // The answer failed: the entry stays as needs_clarification (still tappable,
    // never a dead end), and the failure is surfaced rather than swallowed.
    expect(answerClarification).toHaveBeenCalled();
    expect(hasA11yLabel(tree, "milk, needs a detail, uncounted")).toBe(true);
    expect(textContent(tree)).toContain("That entry couldn't be saved.");
  });

  it("keeps the resolved entry advanced after a poll re-fetches the processing event", async () => {
    jest.useFakeTimers();
    try {
      const needsClar = event({
        id: "a",
        raw_text: "milk",
        status: "needs_clarification",
      });
      const processing = event({
        id: "a",
        raw_text: "milk",
        status: "processing",
      });
      // Initial load returns the needs_clarification row; after the answer
      // advances it server-side, every subsequent poll returns the processing
      // event for the SAME id.
      const load = jest
        .fn()
        .mockResolvedValueOnce([needsClar])
        .mockResolvedValue([processing]);
      const answerClarification = jest.fn().mockResolvedValue(processing);
      const getClarification = jest.fn().mockResolvedValue({
        questions: [
          { id: "q1", text: "What kind of milk?", options: ["Whole", "2%", "Skim"] },
        ],
      });
      const tree = mount(
        <TodayScreen
          session={SESSION}
          load={load}
          answerClarification={answerClarification}
          getClarification={getClarification}
          useActive={() => true}
          pollIntervalMs={1000}
        />,
      );
      await act(async () => {});

      await act(async () => {
        press(tree, "milk, needs a detail, uncounted");
      });
      await act(async () => {
        press(tree, "2%");
      });

      // The event is processing → polling runs and re-fetches the same event
      // (now processing). It must stay advanced in place, never revert to the
      // needs-a-detail treatment and never appear twice.
      act(() => jest.advanceTimersByTime(1000));
      await act(async () => {});

      expect(hasA11yLabel(tree, "milk, needs a detail, uncounted")).toBe(false);
    } finally {
      jest.useRealTimers();
    }
  });

  it("fetches the clarification read and shows Fatty's real question + quick-pick chips", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "peanut butter", status: "needs_clarification" }),
      ]);
    const getClarification = jest.fn().mockResolvedValue({
      questions: [
        {
          id: "q1",
          text: "How much peanut butter?",
          options: ["1 tbsp", "2 tbsp"],
        },
        { id: "q2", text: "Smooth or crunchy?", options: [] },
      ],
    });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "peanut butter, needs a detail, uncounted");
    });

    // The read is scoped to the tapped event, and the primary question is shown
    // verbatim — not the generic "We need a detail…" fallback.
    expect(getClarification).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "a",
    );
    expect(textContent(tree)).toContain("How much peanut butter?");
    expect(textContent(tree)).not.toContain("We need a detail");
    // The payload's candidate options render as tappable quick-pick chips.
    expect(hasA11yLabel(tree, "1 tbsp")).toBe(true);
    expect(hasA11yLabel(tree, "2 tbsp")).toBe(true);
    // The free-text fallback stays reachable alongside the chips.
    expect(hasA11yLabel(tree, "Your answer")).toBe(true);
    expect(hasA11yLabel(tree, "Submit answer")).toBe(true);
  });

  it("falls back to the generic prompt + free-text when the read returns no question", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const getClarification = jest.fn().mockResolvedValue({ questions: [] });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });

    // No persisted question → the generic prompt + free-text fallback remain
    // usable; the user is never blocked.
    expect(textContent(tree)).toContain("We need a detail");
    expect(hasA11yLabel(tree, "Your answer")).toBe(true);
    expect(hasA11yLabel(tree, "Submit answer")).toBe(true);
  });

  it("keeps the free-text fallback usable when the clarification read fails", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const getClarification = jest
      .fn()
      .mockRejectedValue(new LogEventApiError(404, "We couldn't find your log."));
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });

    // A failed read never blocks the flow: the fallback prompt + free-text stand.
    expect(textContent(tree)).toContain("We need a detail");
    expect(hasA11yLabel(tree, "Your answer")).toBe(true);
  });

  it("re-reads the question id at submit time so a fallback answer resolves after a failed read", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const answerClarification = jest
      .fn()
      .mockResolvedValue(
        event({ id: "a", raw_text: "milk", status: "processing" }),
      );
    // The sheet-opening read fails (transient), so no question id is stashed on
    // the sheet target; the submit-time re-read succeeds.
    const getClarification = jest
      .fn()
      .mockRejectedValueOnce(new LogEventApiError(404, "We couldn't find your log."))
      .mockResolvedValue({
        questions: [{ id: "q1", text: "What kind of milk?", options: [] }],
      });
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        answerClarification={answerClarification}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });
    typeInto(tree, "Your answer", "Oat milk");
    await act(async () => {
      press(tree, "Submit answer");
    });

    // The free-text fallback genuinely submits — never dropped on the floor: the
    // question id is re-read at submit time and the answer travels the round-trip.
    expect(getClarification).toHaveBeenCalledTimes(2);
    expect(answerClarification).toHaveBeenCalledWith(
      expect.objectContaining({ userId: SESSION!.userId }),
      "a",
      "q1",
      "Oat milk",
    );
    expect(hasA11yLabel(tree, "milk, needs a detail, uncounted")).toBe(false);
  });

  it("surfaces the failure and keeps the row actionable when the submit-time re-read also fails", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const answerClarification = jest.fn();
    const getClarification = jest
      .fn()
      .mockRejectedValue(new LogEventApiError(404, "We couldn't find your log."));
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        answerClarification={answerClarification}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });
    typeInto(tree, "Your answer", "Oat milk");
    await act(async () => {
      press(tree, "Submit answer");
    });

    // Both reads failed: the failure is surfaced, nothing is submitted against a
    // fabricated id, and the row stays needs-a-detail — tappable, never a dead end.
    expect(answerClarification).not.toHaveBeenCalled();
    expect(textContent(tree)).toContain("We couldn't find your log.");
    expect(hasA11yLabel(tree, "milk, needs a detail, uncounted")).toBe(true);
  });

  it("surfaces an honest error when the event has no persisted question to answer", async () => {
    const load = jest
      .fn()
      .mockResolvedValue([
        event({ id: "a", raw_text: "milk", status: "needs_clarification" }),
      ]);
    const answerClarification = jest.fn();
    // Both the opening read and the submit-time re-read return an empty payload.
    const getClarification = emptyClarification();
    const tree = mount(
      <TodayScreen
        session={SESSION}
        load={load}
        answerClarification={answerClarification}
        getClarification={getClarification}
        useActive={INACTIVE}
      />,
    );
    await act(async () => {});

    await act(async () => {
      press(tree, "milk, needs a detail, uncounted");
    });
    typeInto(tree, "Your answer", "Oat milk");
    await act(async () => {
      press(tree, "Submit answer");
    });

    // No question exists server-side, so there is nothing to answer against:
    // say so plainly and leave the row actionable rather than dead-ending.
    expect(answerClarification).not.toHaveBeenCalled();
    expect(textContent(tree)).toContain(
      "We couldn't load the question. Reopen the entry and try again.",
    );
    expect(hasA11yLabel(tree, "milk, needs a detail, uncounted")).toBe(true);
  });
});
