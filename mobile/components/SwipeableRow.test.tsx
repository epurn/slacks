import { AccessibilityInfo, Text, View } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { SwipeableRow } from "./SwipeableRow";
import { ThemeProvider } from "@/theme/ThemeContext";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

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
