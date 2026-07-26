/**
 * Focused tests for the Today composer view block's attach affordance (FTY-383):
 * the attach action's disabled (offline / signed-out / submitting) states and the
 * calm attach-error line. The full attach → submit flow is covered through the
 * real screen in `TodayScreenImageSubmit.test.tsx`.
 *
 * Plus the FTY-432 layout guarantees: the field owns a full-width line of its
 * own at a roomy resting height, and all four actions stay reachable and wired
 * on the row beneath it.
 */

import { StyleSheet } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

import {
  COMPOSER_INPUT_MAX_HEIGHT,
  COMPOSER_INPUT_MIN_HEIGHT,
  TodayComposer,
} from "./TodayComposer";
import type { ComposerImage } from "./useComposerImages";
import type { ApiSession } from "@/state/session";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

beforeEach(() => mockReduceMotion(false));

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

const SESSION: ApiSession = { baseUrl: "https://x.test", token: "t", userId: "u1" };

const IMAGE: ComposerImage = {
  uri: "file:///a.jpg",
  name: "a.jpg",
  type: "image/jpeg",
  size: 100,
};

function render(overrides: Partial<React.ComponentProps<typeof TodayComposer>> = {}): ReactTestRenderer {
  const inputRef = { current: null };
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 390, height: 844 },
          insets: { top: 47, left: 0, right: 0, bottom: 34 },
        }}
      >
        <TodayComposer
          inputRef={inputRef}
          text=""
          onChangeText={jest.fn()}
          submitting={false}
          canSubmit={false}
          apiSession={SESSION}
          searchSavedFoods={jest.fn()}
          onSelectSavedFood={jest.fn()}
          suggestions={[]}
          onSelectSuggestion={jest.fn()}
          onScan={jest.fn()}
          onCaptureLabel={jest.fn()}
          onSubmit={jest.fn()}
          submitError={null}
          images={[]}
          onAttach={jest.fn()}
          onRemoveImage={jest.fn()}
          attachDisabled={false}
          attachError={null}
          {...overrides}
        />
      </SafeAreaProvider>,
    );
  });
  return tree;
}

function attachNode(tree: ReactTestRenderer) {
  return tree.root.find(
    (n) => n.props.accessibilityLabel === "Attach photo" && typeof n.props.onPress === "function",
  );
}

function textOf(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

describe("TodayComposer attach affordance", () => {
  it("enables attach when online and signed in", () => {
    const tree = render();
    expect(attachNode(tree).props.accessibilityState).toEqual({ disabled: false });
  });

  it("disables attach when offline (image submits are online-only)", () => {
    const tree = render({ attachDisabled: true });
    expect(attachNode(tree).props.accessibilityState).toEqual({ disabled: true });
  });

  it("disables attach while a submit is in flight", () => {
    const tree = render({ submitting: true });
    expect(attachNode(tree).props.accessibilityState).toEqual({ disabled: true });
  });

  it("disables attach when signed out", () => {
    const tree = render({ apiSession: null });
    expect(attachNode(tree).props.accessibilityState).toEqual({ disabled: true });
  });

  it("renders the calm attach error as an alert", () => {
    const tree = render({ attachError: "You can attach up to 4 photos." });
    expect(textOf(tree)).toContain("You can attach up to 4 photos.");
    expect(
      tree.root.findAll(
        (n) =>
          n.props.accessibilityRole === "alert" &&
          n.props.children === "You can attach up to 4 photos.",
      ).length,
    ).toBeGreaterThan(0);
  });

  it("renders a thumbnail with a remove control for each attached image", () => {
    const tree = render({ images: [IMAGE] });
    expect(
      tree.root.findAll((n) => n.props.accessibilityLabel === "Attached photo 1").length,
    ).toBeGreaterThan(0);
    expect(
      tree.root.findAll((n) => n.props.accessibilityLabel === "Remove photo 1").length,
    ).toBeGreaterThan(0);
  });
});

function inputNode(tree: ReactTestRenderer) {
  return tree.root.find((n) => n.props.testID === "today-composer-input");
}

function inputStyle(tree: ReactTestRenderer): Record<string, unknown> {
  return (StyleSheet.flatten(inputNode(tree).props.style) ?? {}) as Record<string, unknown>;
}

function actionNode(tree: ReactTestRenderer, label: string) {
  return tree.root.find(
    (n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function",
  );
}

describe("TodayComposer layout (FTY-432)", () => {
  it("gives the field its own full-width line — it no longer shares a row with the actions", () => {
    const tree = render();
    const style = inputStyle(tree);
    // Not flexed against sibling buttons: the field stretches across the
    // composer column instead of splitting a row with four 44 pt actions.
    expect(style.flex).toBeUndefined();
    expect(style.alignSelf).toBe("stretch");

    // The composer container that holds both the field and the action row is a
    // column, so no action button sits on the field's line.
    const holders = tree.root.findAll(
      (n) =>
        typeof n.type === "string" &&
        n.props.style !== undefined &&
        n.findAll((c) => c.props.testID === "today-composer-input").length > 0 &&
        n.findAll((c) => c.props.accessibilityLabel === "Add entry").length > 0,
    );
    // Innermost host view holding both the field and the Add button.
    const container = holders[holders.length - 1];
    expect(
      (StyleSheet.flatten(container.props.style) as { flexDirection?: string })?.flexDirection,
    ).toBe("column");
  });

  it("rests visibly taller than the old 44 pt slot and keeps the multiline growth ceiling", () => {
    const style = inputStyle(render());
    expect(style.minHeight).toBe(COMPOSER_INPUT_MIN_HEIGHT);
    expect(COMPOSER_INPUT_MIN_HEIGHT).toBeGreaterThan(44);
    expect(style.maxHeight).toBe(COMPOSER_INPUT_MAX_HEIGHT);
    // Breathing room around one line of 17 pt body type.
    expect(style.paddingVertical as number).toBeGreaterThan(12);
    expect(inputNode(render()).props.multiline).toBe(true);
  });

  it("keeps the E2E selectors stable (Maestro flows select by these)", () => {
    const tree = render();
    expect(inputNode(tree).props.accessibilityLabel).toBe("Log food or exercise");
    expect(inputNode(tree).props.placeholder).toBe("Add food or exercise…");
    for (const label of ["Attach photo", "Scan barcode", "Capture label", "Add entry"]) {
      expect(actionNode(tree, label)).toBeTruthy();
    }
  });

  it("keeps all four actions reachable and wired on the row beneath the field", () => {
    const onAttach = jest.fn();
    const onScan = jest.fn();
    const onCaptureLabel = jest.fn();
    const onSubmit = jest.fn();
    const tree = render({ onAttach, onScan, onCaptureLabel, onSubmit, canSubmit: true });

    for (const [label, handler] of [
      ["Attach photo", onAttach],
      ["Scan barcode", onScan],
      ["Capture label", onCaptureLabel],
      ["Add entry", onSubmit],
    ] as const) {
      const node = actionNode(tree, label);
      expect(node.props.accessibilityState).toEqual({ disabled: false });
      act(() => {
        node.props.onPress();
      });
      expect(handler).toHaveBeenCalledTimes(1);
    }
  });

  it("keeps every action at the 44 pt minimum tap target", () => {
    const tree = render({ canSubmit: true });
    for (const label of ["Attach photo", "Scan barcode", "Capture label", "Add entry"]) {
      const style = StyleSheet.flatten(actionNode(tree, label).props.style) as {
        minHeight?: number;
      };
      expect(style.minHeight).toBeGreaterThanOrEqual(44);
    }
  });
});
