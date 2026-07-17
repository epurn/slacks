import React from "react";
import { act, create } from "react-test-renderer";
import { AccessibilityInfo, Animated, View } from "react-native";

import {
  reducedMotionDuration,
  usePulse,
  useReduceMotion,
  useResolveFade,
} from "./motion";
import {
  cleanupReactTestRenderers,
  trackReactTestRenderer,
} from "@/testUtils/reactTestRenderer";

// FTY-379: the reduce-motion gate must never leave content stuck hidden or
// permanently suppress motion because the async accessibility read was slow.
// These tests drive the hooks with a *controllable* read: unresolved (in
// flight), resolved off/on, or never resolving at all.

/** Deadline (ms) after which useResolveFade reveals despite an unsettled read. */
const READ_DEADLINE_MS = 400;

type ReduceMotionListener = (enabled: boolean) => void;

/**
 * Stub `AccessibilityInfo.isReduceMotionEnabled` with a promise the test
 * resolves by hand (or never resolves, for the hung-read scenario), and capture
 * the `reduceMotionChanged` listener so a mid-session toggle can be emitted.
 */
function stubReduceMotionRead(): {
  resolve: (enabled: boolean) => Promise<void>;
  emitChange: (enabled: boolean) => void;
} {
  let resolveRead: (enabled: boolean) => void = () => {};
  const read = new Promise<boolean>((r) => {
    resolveRead = r;
  });
  let listener: ReduceMotionListener | undefined;
  jest.spyOn(AccessibilityInfo, "isReduceMotionEnabled").mockReturnValue(read);
  jest.spyOn(AccessibilityInfo, "addEventListener").mockImplementation(
    ((event: string, handler: ReduceMotionListener) => {
      if (event === "reduceMotionChanged") listener = handler;
      return { remove: jest.fn() };
    }) as never,
  );
  return {
    resolve: async (enabled) => {
      resolveRead(enabled);
      await act(async () => {});
    },
    emitChange: (enabled) => {
      act(() => listener?.(enabled));
    },
  };
}

/**
 * Replace `Animated.timing` / `Animated.spring` with synchronous fakes that
 * jump the driven value to `toValue` on `start()`. Lets tests assert both the
 * branch taken (spring vs fade) and the value the user actually ends up seeing.
 */
function spyOnAnimations(): {
  timing: jest.SpyInstance;
  spring: jest.SpyInstance;
} {
  const instant = (
    value: Animated.Value | Animated.ValueXY,
    config: { toValue: unknown },
  ): Animated.CompositeAnimation => ({
    start: (cb?: Animated.EndCallback) => {
      (value as Animated.Value).setValue(config.toValue as number);
      cb?.({ finished: true });
    },
    stop: jest.fn(),
    reset: jest.fn(),
  });
  const timing = jest
    .spyOn(Animated, "timing")
    .mockImplementation(instant as never);
  const spring = jest
    .spyOn(Animated, "spring")
    .mockImplementation(instant as never);
  return { timing, spring };
}

function currentValue(value: Animated.Value): number {
  return (value as unknown as { __getValue: () => number }).__getValue();
}

// ─── Hook hosts (react-test-renderer has no renderHook) ──────────────────────
// Each host renders its hook's return value into the tree as a `probe` prop on
// a View, so tests read it back via findByProps — no render-time side effects.

function FadeHost({ active }: { active: boolean }) {
  const opacity = useResolveFade(active);
  return React.createElement(View, { testID: "probe", probe: opacity } as never);
}

function GateHost() {
  const reduceMotion = useReduceMotion();
  return React.createElement(View, {
    testID: "probe",
    probe: reduceMotion,
  } as never);
}

function PulseHost() {
  const pulse = usePulse();
  return React.createElement(View, { testID: "probe", probe: pulse } as never);
}

function mount(element: React.ReactElement) {
  let tree: ReturnType<typeof create> | null = null;
  act(() => {
    tree = create(element);
  });
  return trackReactTestRenderer(tree!);
}

function probe<T>(tree: ReturnType<typeof mount>): T {
  return tree.root.findByProps({ testID: "probe" }).props["probe"] as T;
}

beforeEach(() => {
  jest.useFakeTimers();
});

afterEach(() => {
  cleanupReactTestRenderers();
  jest.useRealTimers();
  jest.restoreAllMocks();
});

// ─── useReduceMotion — the gate itself ────────────────────────────────────────

describe("useReduceMotion", () => {
  it("treats a still-unresolved read as reduced (the calm default)", () => {
    stubReduceMotionRead();
    const tree = mount(React.createElement(GateHost));
    expect(probe<boolean>(tree)).toBe(true);
  });

  it("engages the motion-on path once the read resolves off", async () => {
    const read = stubReduceMotionRead();
    const tree = mount(React.createElement(GateHost));
    await read.resolve(false);
    expect(probe<boolean>(tree)).toBe(false);
  });

  it("stays reduced when the read resolves on, and honours a mid-session toggle", async () => {
    const read = stubReduceMotionRead();
    const tree = mount(React.createElement(GateHost));
    await read.resolve(true);
    expect(probe<boolean>(tree)).toBe(true);
    read.emitChange(false);
    expect(probe<boolean>(tree)).toBe(false);
  });
});

// ─── useResolveFade — never leave a resolved row hidden ──────────────────────

describe("useResolveFade", () => {
  it("reveals to full opacity even when the reduce-motion read never resolves", () => {
    stubReduceMotionRead();
    const { timing, spring } = spyOnAnimations();
    const tree = mount(React.createElement(FadeHost, { active: true }));
    const opacity = probe<Animated.Value>(tree);

    // Armed and waiting on the read: hidden, and calm — nothing plays early.
    expect(currentValue(opacity)).toBe(0);
    act(() => {
      jest.advanceTimersByTime(READ_DEADLINE_MS - 1);
    });
    expect(timing).not.toHaveBeenCalled();

    // Deadline: the row reveals with the no-motion fade — never a spring,
    // because the setting is still unknown.
    act(() => {
      jest.advanceTimersByTime(1);
    });
    expect(timing).toHaveBeenCalledTimes(1);
    expect(timing.mock.calls[0][1]).toMatchObject({
      toValue: 1,
      duration: reducedMotionDuration,
    });
    expect(spring).not.toHaveBeenCalled();
    expect(currentValue(opacity)).toBe(1);
  });

  it("takes the spring path, not the fade, once the read resolves off", async () => {
    const read = stubReduceMotionRead();
    const { timing, spring } = spyOnAnimations();
    const tree = mount(React.createElement(FadeHost, { active: true }));
    const opacity = probe<Animated.Value>(tree);

    expect(currentValue(opacity)).toBe(0);
    await read.resolve(false);

    expect(spring).toHaveBeenCalledTimes(1);
    expect(spring.mock.calls[0][1]).toMatchObject({ toValue: 1 });
    expect(timing).not.toHaveBeenCalled();
    expect(currentValue(opacity)).toBe(1);

    // The deadline timer was cleared — no second play later.
    act(() => {
      jest.advanceTimersByTime(READ_DEADLINE_MS);
    });
    expect(spring).toHaveBeenCalledTimes(1);
    expect(timing).not.toHaveBeenCalled();
  });

  it("degrades to the simple fade when the read resolves on", async () => {
    const read = stubReduceMotionRead();
    const { timing, spring } = spyOnAnimations();
    const tree = mount(React.createElement(FadeHost, { active: true }));
    const opacity = probe<Animated.Value>(tree);

    await read.resolve(true);

    expect(timing).toHaveBeenCalledTimes(1);
    expect(timing.mock.calls[0][1]).toMatchObject({
      toValue: 1,
      duration: reducedMotionDuration,
    });
    expect(spring).not.toHaveBeenCalled();
    expect(currentValue(opacity)).toBe(1);
  });

  it("does not replay the beat when the read finally settles after the deadline reveal", async () => {
    const read = stubReduceMotionRead();
    const { timing, spring } = spyOnAnimations();
    const tree = mount(React.createElement(FadeHost, { active: true }));
    const opacity = probe<Animated.Value>(tree);

    act(() => {
      jest.advanceTimersByTime(READ_DEADLINE_MS);
    });
    expect(currentValue(opacity)).toBe(1);

    await read.resolve(false);

    // The fade played once; a late resolution must not re-hide or re-animate.
    expect(timing).toHaveBeenCalledTimes(1);
    expect(spring).not.toHaveBeenCalled();
    expect(currentValue(opacity)).toBe(1);
  });

  it("does not arm the reveal timer for a row that is not resolving", () => {
    stubReduceMotionRead();
    const { timing, spring } = spyOnAnimations();
    const tree = mount(React.createElement(FadeHost, { active: false }));
    const opacity = probe<Animated.Value>(tree);

    expect(currentValue(opacity)).toBe(1);
    act(() => {
      jest.advanceTimersByTime(READ_DEADLINE_MS);
    });
    expect(timing).not.toHaveBeenCalled();
    expect(spring).not.toHaveBeenCalled();
  });
});

// ─── usePulse — degrade while unknown, spring once known off ─────────────────

describe("usePulse", () => {
  it("degrades to an opacity fade while the read is unresolved, then springs once it resolves off", async () => {
    const read = stubReduceMotionRead();
    const { timing, spring } = spyOnAnimations();
    const tree = mount(React.createElement(PulseHost));

    // Setting unknown → the calm default: a fade, no scale motion.
    act(() => {
      probe<ReturnType<typeof usePulse>>(tree).pulse();
    });
    expect(timing).toHaveBeenCalledTimes(2);
    expect(spring).not.toHaveBeenCalled();

    // Setting known off → the real beat: the spring scale bump.
    await read.resolve(false);
    act(() => {
      probe<ReturnType<typeof usePulse>>(tree).pulse();
    });
    expect(spring).toHaveBeenCalledTimes(2);
    expect(timing).toHaveBeenCalledTimes(2);
  });
});
