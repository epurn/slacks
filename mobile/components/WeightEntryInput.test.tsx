import { act, create, type ReactTestRenderer } from "react-test-renderer";

import { WeightEntryInput } from "./WeightEntryInput";

function render(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(element);
  });
  return tree;
}

function inputNode(tree: ReactTestRenderer, label: string) {
  return tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onChangeText === "function",
  );
}

function pressButton(tree: ReactTestRenderer, label: string) {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
  act(() => {
    node.props.onPress();
  });
}

function textContent(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

describe("WeightEntryInput — metric", () => {
  it("renders a weight input labelled with the unit", () => {
    const tree = render(
      <WeightEntryInput
        unitsPreference="metric"
        submitting={false}
        submitError={null}
        onSubmit={jest.fn()}
      />,
    );
    const input = inputNode(tree, "Weight in kg");
    expect(input).toBeTruthy();
    expect(textContent(tree)).toContain("kg");
  });

  it("calls onSubmit with the parsed numeric value when Log weight is pressed", () => {
    const onSubmit = jest.fn();
    const tree = render(
      <WeightEntryInput
        unitsPreference="metric"
        submitting={false}
        submitError={null}
        onSubmit={onSubmit}
      />,
    );

    act(() => {
      inputNode(tree, "Weight in kg").props.onChangeText("70.5");
    });
    pressButton(tree, "Log weight");

    expect(onSubmit).toHaveBeenCalledTimes(1);
    expect(onSubmit).toHaveBeenCalledWith(70.5);
  });

  it("disables the button when the input is empty", () => {
    const onSubmit = jest.fn();
    const tree = render(
      <WeightEntryInput
        unitsPreference="metric"
        submitting={false}
        submitError={null}
        onSubmit={onSubmit}
      />,
    );
    const button = tree.root.find(
      (n) => n.props.accessibilityLabel === "Log weight",
    );
    expect(button.props.accessibilityState.disabled).toBe(true);
    expect(button.props.disabled).toBe(true);
  });

  it("disables the button when submitting", () => {
    const tree = render(
      <WeightEntryInput
        unitsPreference="metric"
        submitting
        submitError={null}
        onSubmit={jest.fn()}
      />,
    );
    act(() => {
      // Enter a value — button still disabled because submitting=true
      inputNode(tree, "Weight in kg").props.onChangeText("80");
    });
    const button = tree.root.find(
      (n) => n.props.accessibilityLabel === "Log weight",
    );
    expect(button.props.disabled).toBe(true);
  });

  it("does not call onSubmit when weight is zero", () => {
    const onSubmit = jest.fn();
    const tree = render(
      <WeightEntryInput
        unitsPreference="metric"
        submitting={false}
        submitError={null}
        onSubmit={onSubmit}
      />,
    );
    act(() => {
      inputNode(tree, "Weight in kg").props.onChangeText("0");
    });
    pressButton(tree, "Log weight");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("does not call onSubmit when weight is non-numeric", () => {
    const onSubmit = jest.fn();
    const tree = render(
      <WeightEntryInput
        unitsPreference="metric"
        submitting={false}
        submitError={null}
        onSubmit={onSubmit}
      />,
    );
    act(() => {
      inputNode(tree, "Weight in kg").props.onChangeText("abc");
    });
    pressButton(tree, "Log weight");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("displays a submit error message", () => {
    const tree = render(
      <WeightEntryInput
        unitsPreference="metric"
        submitting={false}
        submitError="Could not save your weight."
        onSubmit={jest.fn()}
      />,
    );
    expect(textContent(tree)).toContain("Could not save your weight.");
  });

  it("does not echo a weight value into any visible error", () => {
    const tree = render(
      <WeightEntryInput
        unitsPreference="metric"
        submitting={false}
        submitError="Could not save (status 422)."
        onSubmit={jest.fn()}
      />,
    );
    // The error message should not contain the user's weight value
    act(() => {
      inputNode(tree, "Weight in kg").props.onChangeText("75.3");
    });
    expect(textContent(tree)).not.toContain("75.3");
  });
});

// ─────────────────────────────────────────────────────────────────────────────
// Late-arriving seed value (FTY-265): the visual-review `weight.sheet` seam
// opens WeightLogSheet before Trends' own weight-entries read resolves, so
// `initialValue` starts `undefined` and updates once the read settles —
// unlike the "+ Log weight" press, which is only reachable after that data has
// already loaded. Without this, the field stayed on the blank placeholder
// forever once mounted pristine, even after a real seed value arrived.
// ─────────────────────────────────────────────────────────────────────────────

describe("WeightEntryInput — late-arriving seed value (FTY-265)", () => {
  it("fills the field once a seed value arrives after mount, while still pristine", () => {
    const tree = render(
      <WeightEntryInput
        unitsPreference="metric"
        submitting={false}
        submitError={null}
        onSubmit={jest.fn()}
      />,
    );
    expect(inputNode(tree, "Weight in kg").props.value).toBe("");

    act(() => {
      tree.update(
        <WeightEntryInput
          unitsPreference="metric"
          submitting={false}
          submitError={null}
          onSubmit={jest.fn()}
          initialValue={74.8}
        />,
      );
    });

    expect(inputNode(tree, "Weight in kg").props.value).toBe("74.8");
  });

  it("does not clobber text the user already typed before the seed value arrives", () => {
    const tree = render(
      <WeightEntryInput
        unitsPreference="metric"
        submitting={false}
        submitError={null}
        onSubmit={jest.fn()}
      />,
    );
    act(() => {
      inputNode(tree, "Weight in kg").props.onChangeText("60");
    });

    act(() => {
      tree.update(
        <WeightEntryInput
          unitsPreference="metric"
          submitting={false}
          submitError={null}
          onSubmit={jest.fn()}
          initialValue={74.8}
        />,
      );
    });

    expect(inputNode(tree, "Weight in kg").props.value).toBe("60");
  });
});

describe("WeightEntryInput — imperial", () => {
  it("renders a weight input labelled in lb", () => {
    const tree = render(
      <WeightEntryInput
        unitsPreference="imperial"
        submitting={false}
        submitError={null}
        onSubmit={jest.fn()}
      />,
    );
    expect(inputNode(tree, "Weight in lb")).toBeTruthy();
    expect(textContent(tree)).toContain("lb");
  });

  it("calls onSubmit with the raw lb value (conversion is done server-side)", () => {
    const onSubmit = jest.fn();
    const tree = render(
      <WeightEntryInput
        unitsPreference="imperial"
        submitting={false}
        submitError={null}
        onSubmit={onSubmit}
      />,
    );
    act(() => {
      inputNode(tree, "Weight in lb").props.onChangeText("155");
    });
    pressButton(tree, "Log weight");
    expect(onSubmit).toHaveBeenCalledWith(155);
  });
});
