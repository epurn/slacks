/**
 * FTY-366: ChangeMatchPanel error-banner and affordance states.
 *
 * The re-resolve error banner must be announced (alert role), show exactly the
 * message the client mapped, and never leave the user with an inert dead end:
 * with an error showing, the candidate list stays pressable (pick another) and
 * only an in-flight re-resolve disables it.
 */

import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { ThemeProvider, useTheme } from "@/theme";

import { ChangeMatchPanel } from "./ChangeMatchPanel";
import type { SourceCandidate } from "@/api/corrections";
import { cleanupReactTestRenderers, trackReactTestRenderer } from "@/testUtils/reactTestRenderer";

const CANDIDATE: SourceCandidate = {
  source_type: "trusted_nutrition_database",
  source_ref: "usda_fdc:2345170",
  name: "Sandwich, tuna salad",
  basis: "per_100g",
  calories: 192,
  protein_g: 10,
  carbs_g: 17,
  fat_g: 9,
};

type PanelProps = Partial<React.ComponentProps<typeof ChangeMatchPanel>>;

function Panel(overrides: PanelProps) {
  const { colors } = useTheme();
  return (
    <ChangeMatchPanel
      query=""
      onQueryChange={jest.fn()}
      candidates={[CANDIDATE]}
      loading={false}
      error={null}
      reResolving={false}
      reResolveError={null}
      onPickCandidate={jest.fn()}
      onCancel={jest.fn()}
      colors={colors}
      {...overrides}
    />
  );
}

function mount(overrides: PanelProps): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(
      <ThemeProvider override="light">
        <Panel {...overrides} />
      </ThemeProvider>,
    );
  });
  return trackReactTestRenderer(tree);
}

afterEach(() => {
  cleanupReactTestRenderers();
});

describe("ChangeMatchPanel re-resolve error banner", () => {
  it("shows the mapped message with an alert role", () => {
    const message =
      "That match needs to know how much you had. Update the amount, then try the match again.";
    const tree = mount({ reResolveError: message });

    const banner = tree.root.find(
      (n) => n.props.accessibilityRole === "alert" && n.props.children === message,
    );
    expect(banner).toBeDefined();
  });

  it("keeps the candidate list pressable while an error is showing (pick another)", () => {
    const onPickCandidate = jest.fn();
    const tree = mount({
      reResolveError: "That match couldn't be applied. Pick a different match or search again.",
      onPickCandidate,
    });

    const row = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Select Sandwich, tuna salad, 192 kcal per 100g" &&
        typeof n.props.onPress === "function",
    );
    expect(row.props.accessibilityState).toEqual({ disabled: false });
    act(() => {
      row.props.onPress();
    });
    expect(onPickCandidate).toHaveBeenCalledWith(CANDIDATE);
  });

  it("disables candidate rows only while a re-resolve is in flight", () => {
    const tree = mount({ reResolving: true });

    const row = tree.root.find(
      (n) => n.props.accessibilityLabel === "Select Sandwich, tuna salad, 192 kcal per 100g",
    );
    expect(row.props.accessibilityState).toEqual({ disabled: true });
  });
});
