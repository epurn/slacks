import {
  AccessibilityInfo,
  Animated,
  Text,
  View,
  type PanResponderGestureState,
} from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import {
  SwipeableRow,
  buildSwipeResponderConfig,
  shouldClaimHorizontalSwipe,
} from "./SwipeableRow";
import { ThemeProvider } from "@/theme/ThemeContext";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

/** Build a config with spies + a `settle` that latches the offset like the real one. */
function makeConfig(startOffset = 0) {
  const offset = { current: startOffset };
  const translateX = new Animated.Value(startOffset);
  const settle = jest.fn((toValue: number) => {
    offset.current = toValue;
  });
  const setScrollLocked = jest.fn();
  const config = buildSwipeResponderConfig({
    offset,
    translateX,
    settle,
    setScrollLocked,
  });
  return { config, offset, translateX, settle, setScrollLocked };
}

/** Minimal synthetic gesture state — only the fields the arbitration reads. */
function gesture(dx: number, dy: number): PanResponderGestureState {
  return { dx, dy } as PanResponderGestureState;
}

/** A synthetic responder event; the handlers never read it. */
const EVT = {} as never;

/** Read an Animated.Value's current numeric value in the test environment. */
function valueOf(v: Animated.Value): number {
  return (v as unknown as { __getValue: () => number }).__getValue();
}

beforeEach(() => {
  // Reduce Motion on → the reveal settles via setValue (no async spring), so no
  // animation loop leaks past `act` in the test environment.
  mockReduceMotion(true);
});

afterEach(() => {
  jest.restoreAllMocks();
});

function renderRow(
  onDelete: () => void,
  label = "Delete Greek yogurt",
): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <ThemeProvider override="light">
        <SwipeableRow
          onDelete={onDelete}
          deleteAccessibilityLabel={label}
          deleteAnnouncement="Entry removed"
        >
          {(a11y) => (
            <View
              testID="child-row"
              accessible
              accessibilityLabel="Greek yogurt, 150 kcal"
              {...a11y}
            >
              <Text>Greek yogurt</Text>
            </View>
          )}
        </SwipeableRow>
      </ThemeProvider>,
    );
  });
  return tree;
}

describe("SwipeableRow (FTY-322)", () => {
  it("reveals a destructive Delete button that commits on press", () => {
    const onDelete = jest.fn();
    const tree = renderRow(onDelete);

    const button = tree.root.find(
      (n) => n.props.testID === "swipe-delete-action",
    );
    expect(button.props.accessibilityRole).toBe("button");
    expect(button.props.accessibilityLabel).toBe("Delete Greek yogurt");

    act(() => button.props.onPress());
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("announces the removal when the delete commits", () => {
    const announce = jest
      .spyOn(AccessibilityInfo, "announceForAccessibility")
      .mockImplementation(() => {});
    const tree = renderRow(jest.fn());

    act(() =>
      tree.root.find((n) => n.props.testID === "swipe-delete-action").props.onPress(),
    );

    expect(announce).toHaveBeenCalledWith("Entry removed");
  });

  it("hands the child a Delete custom action reachable without the gesture", () => {
    const onDelete = jest.fn();
    const tree = renderRow(onDelete);

    // The child row carries the delete custom action on its own accessible
    // element — the swipe is pointer-only, so VoiceOver reaches Delete here.
    const child = tree.root.find((n) => n.props.testID === "child-row");
    expect(child.props.accessibilityActions).toEqual([
      { name: "delete", label: "Delete" },
    ]);

    act(() =>
      child.props.onAccessibilityAction({
        nativeEvent: { actionName: "delete" },
      }),
    );
    expect(onDelete).toHaveBeenCalledTimes(1);
  });

  it("ignores unrelated accessibility actions", () => {
    const onDelete = jest.fn();
    const tree = renderRow(onDelete);
    const child = tree.root.find((n) => n.props.testID === "child-row");

    act(() =>
      child.props.onAccessibilityAction({
        nativeEvent: { actionName: "activate" },
      }),
    );
    expect(onDelete).not.toHaveBeenCalled();
  });

  it("wires the pan gesture without capturing a plain touch-down", () => {
    const tree = renderRow(jest.fn());
    // The pan handlers are present (the swipe is wired) and the gesture only
    // arms on a clear horizontal move — a touch-down never captures, so the
    // child's own press handler and the enclosing scroll both keep working.
    const content = tree.root.find(
      (n) =>
        typeof n.props.onStartShouldSetResponder === "function" &&
        typeof n.props.onMoveShouldSetResponder === "function",
    );
    expect(content).toBeTruthy();
  });
});

describe("swipe arbitration wins over vertical scroll (FTY-417)", () => {
  it("claims a horizontal-dominant drag past the slop", () => {
    // Clear left drag → claim it (reveal opens); the enclosing scroll yields.
    expect(shouldClaimHorizontalSwipe(-40, 6)).toBe(true);
    expect(shouldClaimHorizontalSwipe(40, -6)).toBe(true);
  });

  it("does not claim a vertical-dominant drag — the scroll wins", () => {
    expect(shouldClaimHorizontalSwipe(6, -40)).toBe(false);
    expect(shouldClaimHorizontalSwipe(-6, 40)).toBe(false);
  });

  it("ignores sub-slop jitter so a near-still touch never claims", () => {
    expect(shouldClaimHorizontalSwipe(-4, 1)).toBe(false);
    expect(shouldClaimHorizontalSwipe(8, 0)).toBe(false); // must exceed the slop
  });

  it("onMoveShouldSetPanResponder gates on the same direction rule", () => {
    const { config } = makeConfig();
    expect(config.onMoveShouldSetPanResponder?.(EVT, gesture(-40, 6))).toBe(true);
    expect(config.onMoveShouldSetPanResponder?.(EVT, gesture(6, -40))).toBe(false);
    // A plain touch-down never claims — taps fall through to the child row.
    expect(config.onStartShouldSetPanResponder?.(EVT, gesture(0, 0))).toBe(false);
  });

  it("refuses to yield the gesture back to the scroll container", () => {
    // The crux of the bug: without this the ScrollView reclaims the pan and the
    // half-open reveal snaps shut. Returning false keeps the responder latched.
    const { config } = makeConfig();
    expect(config.onPanResponderTerminationRequest?.(EVT, gesture(-40, 0))).toBe(
      false,
    );
    // And it blocks the Android native scroll responder for good measure.
    expect(config.onShouldBlockNativeResponder?.(EVT, gesture(-40, 0))).toBe(true);
  });

  it("locks the scroll on grant and unlocks it on release", () => {
    const { config, setScrollLocked } = makeConfig();
    config.onPanResponderGrant?.(EVT, gesture(0, 0));
    expect(setScrollLocked).toHaveBeenLastCalledWith(true);

    config.onPanResponderRelease?.(EVT, gesture(-60, 0));
    expect(setScrollLocked).toHaveBeenLastCalledWith(false);
  });

  it("unlocks the scroll on an OS-forced termination too", () => {
    const { config, setScrollLocked } = makeConfig();
    config.onPanResponderGrant?.(EVT, gesture(0, 0));
    config.onPanResponderTerminate?.(EVT, gesture(-60, 0));
    expect(setScrollLocked).toHaveBeenLastCalledWith(false);
  });

  it("tracks the finger while dragging, clamped to the action width", () => {
    const { config, translateX } = makeConfig();
    config.onPanResponderMove?.(EVT, gesture(-40, 0));
    expect(valueOf(translateX)).toBe(-40);
    // Never overshoot past the action width on the left…
    config.onPanResponderMove?.(EVT, gesture(-200, 0));
    expect(valueOf(translateX)).toBe(-88);
    // …and never past closed on a rightward drag from rest.
    config.onPanResponderMove?.(EVT, gesture(50, 0));
    expect(valueOf(translateX)).toBe(0);
  });

  it("latches open past the threshold and stays open on an ambiguous release", () => {
    const { config, offset, settle } = makeConfig();
    config.onPanResponderGrant?.(EVT, gesture(0, 0));
    config.onPanResponderMove?.(EVT, gesture(-60, 0));
    config.onPanResponderRelease?.(EVT, gesture(-60, 0));
    // Past the half-width threshold → settle fully open and hold that offset.
    expect(settle).toHaveBeenLastCalledWith(-88);
    expect(offset.current).toBe(-88);

    // Now open: a later forced terminate must keep it open, never snap it shut.
    config.onPanResponderTerminate?.(EVT, gesture(0, 0));
    expect(settle).toHaveBeenLastCalledWith(-88);
    expect(offset.current).toBe(-88);
  });

  it("settles closed when the release falls short of the open threshold", () => {
    const { config, offset, settle } = makeConfig();
    config.onPanResponderRelease?.(EVT, gesture(-10, 0));
    expect(settle).toHaveBeenLastCalledWith(0);
    expect(offset.current).toBe(0);
  });

  it("is safe with no scroll-lock provider (isolated row)", () => {
    const offset = { current: 0 };
    const translateX = new Animated.Value(0);
    const config = buildSwipeResponderConfig({
      offset,
      translateX,
      settle: jest.fn(),
      setScrollLocked: null,
    });
    expect(() => config.onPanResponderGrant?.(EVT, gesture(0, 0))).not.toThrow();
    expect(() =>
      config.onPanResponderRelease?.(EVT, gesture(-60, 0)),
    ).not.toThrow();
  });
});
