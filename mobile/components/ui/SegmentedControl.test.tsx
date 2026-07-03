/**
 * Component tests for the shared native SegmentedControl wrapper (FTY-186).
 *
 * The wrapper adapts a value/label option list to the platform
 * `UISegmentedControl`: it renders the labels in order, marks the selected
 * option, forwards the accessibility label, and maps a native segment tap back
 * to the caller's domain value. These are the invariants every migrated call
 * site (Settings units/appearance/cadence/goal, Trends range) relies on.
 */

import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { SegmentedControl } from "./SegmentedControl";

type Units = "metric" | "imperial";

const OPTIONS = [
  { value: "metric" as Units, label: "Metric" },
  { value: "imperial" as Units, label: "Imperial" },
];

/** The first native control host that carries the values + onChange props. */
function findControl(tree: ReactTestRenderer) {
  return tree.root.findAll(
    (n) =>
      n.props.testID === "units" &&
      Array.isArray(n.props.values) &&
      typeof n.props.onChange === "function",
  )[0];
}

function render(selected: Units, onSelect: (v: Units) => void): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <SegmentedControl<Units>
        testID="units"
        accessibilityLabel="Units preference"
        options={OPTIONS}
        selected={selected}
        onSelect={onSelect}
      />,
    );
  });
  return tree;
}

it("renders the option labels in order", () => {
  const tree = render("metric", jest.fn());
  expect(findControl(tree).props.values).toEqual(["Metric", "Imperial"]);
});

it("reflects the selected option as the native selectedIndex", () => {
  const tree = render("imperial", jest.fn());
  expect(findControl(tree).props.selectedIndex).toBe(1);
});

it("forwards the accessibility label to the native control", () => {
  const tree = render("metric", jest.fn());
  expect(findControl(tree).props.accessibilityLabel).toBe("Units preference");
});

it("maps a native segment tap back to the option value", () => {
  const onSelect = jest.fn();
  const tree = render("metric", onSelect);
  act(() => {
    findControl(tree).props.onChange({
      nativeEvent: { selectedSegmentIndex: 1, value: "Imperial" },
    });
  });
  expect(onSelect).toHaveBeenCalledWith("imperial");
});

it("defaults selectedIndex to 0 when the value is not among the options", () => {
  // A stale/unknown value must not blank the control — it falls back to the first
  // segment rather than a -1 native index.
  const tree = render("kelvin" as Units, jest.fn());
  expect(findControl(tree).props.selectedIndex).toBe(0);
});
