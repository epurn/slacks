import { act, create as render, type ReactTestRenderer } from "react-test-renderer";

import { hasPendingWork, isNonTerminal, useIntervalPolling } from "./polling";
import type { LogEventDTO, LogEventStatus } from "@/api/logEvents";

function event(status: LogEventStatus): LogEventDTO {
  return {
    id: status,
    user_id: "u",
    raw_text: "x",
    status,
    created_at: "2026-06-26T08:00:00Z",
    updated_at: "2026-06-26T08:00:00Z",
  };
}

describe("isNonTerminal", () => {
  it("treats only pending and processing as in-flight", () => {
    expect(isNonTerminal("pending")).toBe(true);
    expect(isNonTerminal("processing")).toBe(true);
    expect(isNonTerminal("completed")).toBe(false);
    expect(isNonTerminal("failed")).toBe(false);
    // needs_clarification waits on a user edit, not the server, so it is not polled.
    expect(isNonTerminal("needs_clarification")).toBe(false);
  });
});

describe("hasPendingWork", () => {
  it("is true while any event is non-terminal", () => {
    expect(hasPendingWork([event("completed"), event("pending")])).toBe(true);
  });

  it("is false once every event is terminal (the stop condition)", () => {
    expect(hasPendingWork([event("completed"), event("failed")])).toBe(false);
    expect(hasPendingWork([event("needs_clarification")])).toBe(false);
  });

  it("is false for an empty timeline", () => {
    expect(hasPendingWork([])).toBe(false);
  });
});

// Tiny harness so the hook can be exercised on its own.
function Poller({
  active,
  intervalMs,
  onTick,
}: {
  active: boolean;
  intervalMs: number;
  onTick: () => void;
}) {
  useIntervalPolling(active, intervalMs, onTick);
  return null;
}

describe("useIntervalPolling", () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  function mount(props: {
    active: boolean;
    intervalMs: number;
    onTick: () => void;
  }): ReactTestRenderer {
    let tree!: ReactTestRenderer;
    act(() => {
      tree = render(<Poller {...props} />);
    });
    return tree;
  }

  it("does not fire a leading tick", () => {
    const onTick = jest.fn();
    mount({ active: true, intervalMs: 1000, onTick });
    expect(onTick).toHaveBeenCalledTimes(0);
  });

  it("fires once per interval while active", () => {
    const onTick = jest.fn();
    mount({ active: true, intervalMs: 1000, onTick });
    act(() => jest.advanceTimersByTime(1000));
    expect(onTick).toHaveBeenCalledTimes(1);
    act(() => jest.advanceTimersByTime(2000));
    expect(onTick).toHaveBeenCalledTimes(3);
  });

  it("stops when active goes false and resumes when it goes true again", () => {
    const onTick = jest.fn();
    const tree = mount({ active: true, intervalMs: 1000, onTick });
    act(() => jest.advanceTimersByTime(1000));
    expect(onTick).toHaveBeenCalledTimes(1);

    // Stop: no further ticks while inactive.
    act(() => {
      tree.update(<Poller active={false} intervalMs={1000} onTick={onTick} />);
    });
    act(() => jest.advanceTimersByTime(5000));
    expect(onTick).toHaveBeenCalledTimes(1);

    // Resume: ticking restarts on the active edge.
    act(() => {
      tree.update(<Poller active={true} intervalMs={1000} onTick={onTick} />);
    });
    act(() => jest.advanceTimersByTime(1000));
    expect(onTick).toHaveBeenCalledTimes(2);
  });

  it("clears the interval on unmount", () => {
    const onTick = jest.fn();
    const tree = mount({ active: true, intervalMs: 1000, onTick });
    act(() => tree.unmount());
    act(() => jest.advanceTimersByTime(5000));
    expect(onTick).toHaveBeenCalledTimes(0);
  });

  it("uses the latest callback without restarting the timer", () => {
    const first = jest.fn();
    const second = jest.fn();
    const tree = mount({ active: true, intervalMs: 1000, onTick: first });
    act(() => jest.advanceTimersByTime(500));
    // Swap the callback mid-interval; the timer must not reset.
    act(() => {
      tree.update(<Poller active={true} intervalMs={1000} onTick={second} />);
    });
    act(() => jest.advanceTimersByTime(500));
    expect(first).toHaveBeenCalledTimes(0);
    expect(second).toHaveBeenCalledTimes(1);
  });
});
