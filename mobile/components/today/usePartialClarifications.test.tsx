import { act, create } from "react-test-renderer";

import type { LogEventDTO } from "@/api/logEvents";
import type { ApiSession } from "@/state/session";

import { usePartialClarifications, type QuestionsByEvent } from "./usePartialClarifications";
import { event } from "./todayTestUtils";

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "t",
  userId: "u1",
};

/** Render the hook and expose its latest return value for assertions. */
function renderHook(initial: {
  events: readonly LogEventDTO[];
  getClarification: jest.Mock;
  reloadKey?: number;
}) {
  const captured: { value: QuestionsByEvent } = { value: {} };
  function Harness(props: {
    events: readonly LogEventDTO[];
    getClarification: jest.Mock;
    reloadKey: number;
  }) {
    captured.value = usePartialClarifications({
      apiSession: SESSION,
      events: props.events,
      getClarification: props.getClarification,
      reloadKey: props.reloadKey,
    });
    return null;
  }
  let renderer!: ReturnType<typeof create>;
  act(() => {
    renderer = create(
      <Harness
        events={initial.events}
        getClarification={initial.getClarification}
        reloadKey={initial.reloadKey ?? 0}
      />,
    );
  });
  return {
    captured,
    async update(next: {
      events: readonly LogEventDTO[];
      getClarification: jest.Mock;
      reloadKey?: number;
    }) {
      await act(async () => {
        renderer.update(
          <Harness
            events={next.events}
            getClarification={next.getClarification}
            reloadKey={next.reloadKey ?? 0}
          />,
        );
      });
    },
    unmount() {
      act(() => renderer.unmount());
    },
  };
}

describe("usePartialClarifications (FTY-330)", () => {
  it("fetches open questions only for partially_resolved events", async () => {
    const getClarification = jest.fn().mockResolvedValue({
      questions: [{ id: "q1", text: "How much hummus?", options: [] }],
    });
    const harness = renderHook({
      events: [
        event({ id: "a", status: "partially_resolved" }),
        event({ id: "b", status: "completed" }),
        event({ id: "c", status: "pending" }),
      ],
      getClarification,
    });
    await act(async () => {});

    expect(getClarification).toHaveBeenCalledTimes(1);
    expect(getClarification).toHaveBeenCalledWith(SESSION, "a");
    expect(harness.captured.value).toEqual({
      a: [{ id: "q1", text: "How much hummus?", options: [] }],
    });
    harness.unmount();
  });

  it("keeps the last-known questions when a read fails (no flicker)", async () => {
    const ok = jest.fn().mockResolvedValue({
      questions: [{ id: "q1", text: "How much hummus?", options: [] }],
    });
    const harness = renderHook({
      events: [event({ id: "a", status: "partially_resolved" })],
      getClarification: ok,
    });
    await act(async () => {});
    expect(harness.captured.value.a).toHaveLength(1);

    // A later refresh whose read rejects must not drop the row that is showing.
    const failing = jest.fn().mockRejectedValue(new Error("network"));
    await harness.update({
      events: [event({ id: "a", status: "partially_resolved" })],
      getClarification: failing,
      reloadKey: 1,
    });

    expect(harness.captured.value.a).toEqual([
      { id: "q1", text: "How much hummus?", options: [] },
    ]);
    harness.unmount();
  });

  it("clears questions once no event is partially_resolved", async () => {
    const getClarification = jest.fn().mockResolvedValue({
      questions: [{ id: "q1", text: "How much hummus?", options: [] }],
    });
    const harness = renderHook({
      events: [event({ id: "a", status: "partially_resolved" })],
      getClarification,
    });
    await act(async () => {});
    expect(harness.captured.value.a).toBeDefined();

    // The event advances past partial (answered → processing): its stale question
    // is dropped so the timeline never renders an orphaned pending-question row.
    await harness.update({
      events: [event({ id: "a", status: "processing" })],
      getClarification,
    });
    expect(harness.captured.value).toEqual({});
    harness.unmount();
  });
});
