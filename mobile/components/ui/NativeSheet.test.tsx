/**
 * FTY-227 regression guard for {@link NativeSheet}.
 *
 * The bug: on iOS the native `formSheet` (react-native-screens `ScreenStackItem`)
 * presented its chrome but rendered its body **blank** — the title, provenance
 * block, and Portion stepper never took up any space. Root cause: RNS positions
 * a formSheet's content wrapper as `position: absolute; top/left/right` with no
 * `bottom` (its `absoluteWithNoBottom` path for RN ≥ 0.82 without synchronous
 * screen updates), so the wrapper is sized to intrinsic content height and a
 * `flex: 1` sheet body has no bounded height to fill and collapses to zero.
 *
 * Why this guard is meaningful even though Jest does no native layout: Jest
 * always mounts children into the tree, so a "does the title render" assertion
 * passes even on the broken code (that is exactly why the CI E2E job — Android
 * only, where the Modal fallback gives its body an explicit height — stayed
 * green while iOS was blank). This guard instead asserts the *structural* fix:
 * on iOS the content host that wraps the children carries a bounded, non-zero
 * height derived from the largest detent. It runs on the iOS code path (Platform
 * default is `ios` under jest-expo) and asserts iOS-specific structure, so it
 * cannot silently pass on Android — the `native-sheet-ios-content-host` node
 * only exists on the iOS branch.
 *
 * Platform protected by this guard: **iOS** (the platform the bug reproduces on
 * and the one CI's Android-only E2E cannot exercise).
 */

import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import {
  Dimensions,
  Platform,
  StyleSheet,
  Text,
  View,
  type ViewStyle,
} from "react-native";

import { NativeSheet } from "./NativeSheet";
import {
  cleanupReactTestRenderers,
  trackReactTestRenderer,
} from "@/testUtils/reactTestRenderer";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

const IOS_HOST_ID = "native-sheet-ios-content-host";
const CHILD_ID = "native-sheet-test-child";

function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(element);
  });
  return trackReactTestRenderer(tree);
}

function hostHeight(tree: ReactTestRenderer): ViewStyle["height"] {
  const host = tree.root.find((n) => n.props.testID === IOS_HOST_ID);
  return (StyleSheet.flatten(host.props.style) as ViewStyle).height;
}

function child(scale: string) {
  return (
    <View testID={CHILD_ID} style={{ flex: 1 }}>
      <Text>{scale}</Text>
    </View>
  );
}

beforeEach(() => {
  mockReduceMotion(false);
});

afterEach(() => {
  cleanupReactTestRenderers();
  jest.restoreAllMocks();
});

describe("NativeSheet — iOS content render (FTY-227)", () => {
  it("runs the iOS sheet path under this suite", () => {
    // Documents the platform the guard protects: if the default ever flipped to
    // Android the iOS host below would be absent and every assertion would fail,
    // rather than the guard silently passing.
    expect(Platform.OS).toBe("ios");
  });

  it("wraps children in a bounded, non-zero-height host so a flex body cannot collapse to blank", () => {
    const tree = mount(
      <NativeSheet
        visible
        onClose={jest.fn()}
        detents={[0.5, 1.0]}
        backgroundColor="#fff"
        accessibilityLabel="Turkey breast details"
      >
        {child("body")}
      </NativeSheet>,
    );

    const height = hostHeight(tree);
    // The regression: without the fix the children were a direct child of the
    // (bottom-less, content-sized) RNS wrapper — no bounded height — and the
    // flex body collapsed. A numeric, non-zero height is what keeps it visible.
    expect(typeof height).toBe("number");
    expect(height as number).toBeGreaterThan(0);

    // Sizes to the LARGEST detent (1.0), never the initial one, so the body
    // never undershoots into an empty gap at the large detent.
    const windowHeight = Dimensions.get("window").height;
    expect(height).toBe(Math.round(windowHeight * 1.0));

    // …and the content actually mounts inside that bounded host.
    const host = tree.root.find((n) => n.props.testID === IOS_HOST_ID);
    const nested = host.findAll((n) => n.props.testID === CHILD_ID);
    expect(nested.length).toBeGreaterThanOrEqual(1);
  });

  it("does not force a height on a fitToContents sheet (keeps the compact weight sheet fitting its content)", () => {
    const tree = mount(
      <NativeSheet
        visible
        onClose={jest.fn()}
        detents="fitToContents"
        backgroundColor="#fff"
        accessibilityLabel="Log weight sheet"
      >
        {child("weight")}
      </NativeSheet>,
    );

    // fitToContents must size to its own content — a forced height would break
    // the intended compact sheet. So no explicit height is applied.
    expect(hostHeight(tree)).toBeUndefined();
  });

  it("preserves the native chrome and detent contract on the sheet screen", () => {
    const tree = mount(
      <NativeSheet
        visible
        onClose={jest.fn()}
        detents={[0.5, 1.0]}
        grabberVisible
        backgroundColor="#fff"
        accessibilityLabel="Turkey breast details"
      >
        {child("body")}
      </NativeSheet>,
    );

    const sheetScreen = tree.root.find(
      (n) => typeof n.props.onDismissed === "function",
    );
    expect(sheetScreen.props.accessibilityLabel).toBe("Turkey breast details");
    expect(sheetScreen.props.sheetGrabberVisible).toBe(true);
    expect(sheetScreen.props.sheetAllowedDetents).toEqual([0.5, 1.0]);
  });

  it("forwards a native dismissal to onClose", () => {
    const onClose = jest.fn();
    const tree = mount(
      <NativeSheet
        visible
        onClose={onClose}
        detents={[0.5, 1.0]}
        backgroundColor="#fff"
      >
        {child("body")}
      </NativeSheet>,
    );

    const sheetScreen = tree.root.find(
      (n) => typeof n.props.onDismissed === "function",
    );
    act(() => {
      sheetScreen.props.onDismissed({ nativeEvent: { dismissCount: 1 } });
    });
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

describe("NativeSheet — Android Modal fallback unchanged (FTY-227)", () => {
  const realOS = Platform.OS;
  beforeAll(() => {
    Object.defineProperty(Platform, "OS", { value: "android", configurable: true });
  });
  afterAll(() => {
    Object.defineProperty(Platform, "OS", { value: realOS, configurable: true });
  });

  it("renders content in the Modal fallback with no iOS content host", () => {
    const tree = mount(
      <NativeSheet
        visible
        onClose={jest.fn()}
        detents={[0.5, 1.0]}
        backgroundColor="#fff"
        accessibilityLabel="Turkey breast details"
      >
        {child("body")}
      </NativeSheet>,
    );

    // The Android branch is untouched: the iOS host does not exist there, and
    // the same children render inside the Modal fallback.
    expect(tree.root.findAll((n) => n.props.testID === IOS_HOST_ID).length).toBe(
      0,
    );
    expect(
      tree.root.findAll((n) => n.props.testID === CHILD_ID).length,
    ).toBeGreaterThanOrEqual(1);
  });
});
