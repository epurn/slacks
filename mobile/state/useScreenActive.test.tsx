import { useEffect } from "react";
import { act, create as render } from "react-test-renderer";
import { AppState, type AppStateStatus } from "react-native";

import { useAppForeground } from "./useScreenActive";

// Capture the hook's value out of band (in an effect, not during render) so the
// test can assert on it across app-state transitions.
const sink = { value: false };
function Probe() {
  const active = useAppForeground();
  useEffect(() => {
    sink.value = active;
  }, [active]);
  return null;
}

describe("useAppForeground", () => {
  it("tracks the OS app state across background and foreground", () => {
    let handler!: (state: AppStateStatus) => void;
    const remove = jest.fn();
    const spy = jest
      .spyOn(AppState, "addEventListener")
      .mockImplementation((_type, cb) => {
        handler = cb as (state: AppStateStatus) => void;
        return { remove } as ReturnType<typeof AppState.addEventListener>;
      });

    let tree!: ReturnType<typeof render>;
    act(() => {
      tree = render(<Probe />);
    });

    // Foregrounding reports active; backgrounding pauses.
    act(() => handler("active"));
    expect(sink.value).toBe(true);
    act(() => handler("background"));
    expect(sink.value).toBe(false);
    act(() => handler("active"));
    expect(sink.value).toBe(true);

    // The subscription is cleaned up on unmount.
    act(() => tree.unmount());
    expect(remove).toHaveBeenCalledTimes(1);
    spy.mockRestore();
  });
});
