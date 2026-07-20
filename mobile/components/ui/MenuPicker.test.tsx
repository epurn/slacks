/**
 * Component tests for the shared native MenuPicker (FTY-403).
 *
 * The picker shows the current choice inline and, on the iOS path (the jest-expo
 * default platform), presents the option list through the system
 * `ActionSheetIOS` — never a hand-rolled group. These tests prove the trigger
 * reflects the selection, the menu presents every option full-label, and a
 * native selection maps back to the caller's domain value (with the appended
 * Cancel entry ignored).
 */

import { ActionSheetIOS, Text } from "react-native";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { ThemeProvider } from "@/theme";
import { MenuPicker } from "./MenuPicker";

type Cadence = "daily" | "weekly" | "off";

const OPTIONS = [
  { value: "daily" as Cadence, label: "Daily" },
  { value: "weekly" as Cadence, label: "Weekly" },
  { value: "off" as Cadence, label: "Off" },
];

const showActionSheet = jest
  .spyOn(ActionSheetIOS, "showActionSheetWithOptions")
  .mockImplementation(() => {});

afterEach(() => {
  showActionSheet.mockClear();
});

function render(
  selected: Cadence,
  onSelect: (v: Cadence) => void,
): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <ThemeProvider>
        <MenuPicker<Cadence>
          testID="menu"
          title="Cadence"
          accessibilityLabel="Cadence"
          options={OPTIONS}
          selected={selected}
          onSelect={onSelect}
        />
      </ThemeProvider>,
    );
  });
  return tree;
}

function trigger(tree: ReactTestRenderer) {
  return tree.root.findAll(
    (n) =>
      n.props.testID === "menu" && typeof n.props.onPress === "function",
  )[0]!;
}

it("shows the selected option's label on the trigger", () => {
  const tree = render("weekly", jest.fn());
  const labels = tree.root.findAllByType(Text).map((n) => n.props.children);
  expect(labels).toContain("Weekly");
});

it("exposes the selection in the trigger accessibility label", () => {
  const tree = render("weekly", jest.fn());
  expect(trigger(tree).props.accessibilityLabel).toBe("Cadence, Weekly");
  expect(trigger(tree).props.accessibilityRole).toBe("button");
});

it("presents every option (plus a trailing Cancel) through ActionSheetIOS", () => {
  const tree = render("weekly", jest.fn());
  act(() => {
    trigger(tree).props.onPress();
  });
  const [config] = showActionSheet.mock.calls.at(-1)!;
  expect(config.options).toEqual(["Daily", "Weekly", "Off", "Cancel"]);
  expect(config.cancelButtonIndex).toBe(3);
  expect(config.title).toBe("Cadence");
});

it("maps a native selection back to the caller's domain value", () => {
  const onSelect = jest.fn();
  const tree = render("weekly", onSelect);
  act(() => {
    trigger(tree).props.onPress();
  });
  const [, callback] = showActionSheet.mock.calls.at(-1)!;
  act(() => {
    callback(0); // "Daily"
  });
  expect(onSelect).toHaveBeenCalledWith("daily");
});

it("does not select when the Cancel entry is chosen", () => {
  const onSelect = jest.fn();
  const tree = render("weekly", onSelect);
  act(() => {
    trigger(tree).props.onPress();
  });
  const [, callback] = showActionSheet.mock.calls.at(-1)!;
  act(() => {
    callback(3); // the appended "Cancel"
  });
  expect(onSelect).not.toHaveBeenCalled();
});
