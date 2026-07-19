/**
 * Focused tests for the Today composer view block's attach affordance (FTY-383):
 * the attach action's disabled (offline / signed-out / submitting) states and the
 * calm attach-error line. The full attach → submit flow is covered through the
 * real screen in `TodayScreenImageSubmit.test.tsx`.
 */

import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { TodayComposer } from "./TodayComposer";
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
