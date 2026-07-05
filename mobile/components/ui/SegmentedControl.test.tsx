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

// ─── Per-segment accessibility labels (FTY-222, additive) ────────────────────

type Pace = "gentle" | "steady";

function findPace(tree: ReactTestRenderer) {
  return tree.root.findAll(
    (n) =>
      n.props.testID === "pace" &&
      Array.isArray(n.props.values) &&
      typeof n.props.onChange === "function",
  )[0];
}

function renderPace(
  options: { value: Pace; label: string; accessibilityLabel?: string }[],
): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <SegmentedControl<Pace>
        testID="pace"
        accessibilityLabel="Goal pace"
        options={options}
        selected="steady"
        onSelect={jest.fn()}
      />,
    );
  });
  return tree;
}

it("leaves the visible segment titles untouched when per-segment labels are set", () => {
  const tree = renderPace([
    { value: "gentle", label: "Gentle", accessibilityLabel: "Gentle: slow" },
    { value: "steady", label: "Steady", accessibilityLabel: "Steady: recommended" },
  ]);
  // The short labels remain the tappable titles; descriptions live in a11y only.
  expect(findPace(tree).props.values).toEqual(["Gentle", "Steady"]);
});

it("folds per-segment accessibility labels into the control accessibility label", () => {
  const tree = renderPace([
    { value: "gentle", label: "Gentle", accessibilityLabel: "Gentle: slow" },
    { value: "steady", label: "Steady", accessibilityLabel: "Steady: recommended" },
  ]);
  expect(findPace(tree).props.accessibilityLabel).toBe(
    "Goal pace. Gentle: slow. Steady: recommended",
  );
});

it("keeps the bare control accessibility label when no per-segment labels are given", () => {
  // Additive guarantee: FTY-186 call sites (no per-segment labels) are unchanged.
  const tree = renderPace([
    { value: "gentle", label: "Gentle" },
    { value: "steady", label: "Steady" },
  ]);
  expect(findPace(tree).props.accessibilityLabel).toBe("Goal pace");
});
