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

// ─── Per-option description caption (FTY-222, additive) ──────────────────────

type Pace = "gentle" | "steady";

const PACE_OPTIONS = [
  { value: "gentle" as Pace, label: "Gentle", description: "Gentle: slow" },
  {
    value: "steady" as Pace,
    label: "Steady",
    description: "Steady: recommended",
  },
];

function findPace(tree: ReactTestRenderer) {
  return tree.root.findAll(
    (n) =>
      n.props.testID === "pace" &&
      Array.isArray(n.props.values) &&
      typeof n.props.onChange === "function",
  )[0];
}

/** The visible description caption text, or null when no caption is rendered. */
function captionText(tree: ReactTestRenderer): string | null {
  const nodes = tree.root.findAll((n) => n.props.testID === "pace-caption");
  if (nodes.length === 0) return null;
  return nodes[0].props.children as string;
}

function renderPace(
  options: { value: Pace; label: string; description?: string }[],
  selected: Pace,
): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(
      <SegmentedControl<Pace>
        testID="pace"
        accessibilityLabel="Goal pace"
        options={options}
        selected={selected}
        onSelect={jest.fn()}
      />,
    );
  });
  return tree;
}

it("leaves the visible segment titles untouched when descriptions are set", () => {
  const tree = renderPace(PACE_OPTIONS, "steady");
  // The short labels remain the tappable titles; the description is the caption.
  expect(findPace(tree).props.values).toEqual(["Gentle", "Steady"]);
});

it("renders the selected option's description as a visible caption", () => {
  const tree = renderPace(PACE_OPTIONS, "steady");
  expect(captionText(tree)).toBe("Steady: recommended");
});

it("updates the caption when the selection changes", () => {
  const tree = renderPace(PACE_OPTIONS, "steady");
  act(() => {
    tree.update(
      <SegmentedControl<Pace>
        testID="pace"
        accessibilityLabel="Goal pace"
        options={PACE_OPTIONS}
        selected="gentle"
        onSelect={jest.fn()}
      />,
    );
  });
  expect(captionText(tree)).toBe("Gentle: slow");
});

it("renders no caption when the selected option has no description", () => {
  // Additive guarantee: FTY-186 call sites (no descriptions) render bare.
  const tree = renderPace(
    [
      { value: "gentle", label: "Gentle" },
      { value: "steady", label: "Steady" },
    ],
    "steady",
  );
  expect(captionText(tree)).toBeNull();
});

it("keeps the bare control accessibility label unchanged (additive)", () => {
  // The description surfaces as a caption, never folded into the control label,
  // so FTY-186 call sites keep their exact accessibility label.
  const tree = renderPace(PACE_OPTIONS, "steady");
  expect(findPace(tree).props.accessibilityLabel).toBe("Goal pace");
});
