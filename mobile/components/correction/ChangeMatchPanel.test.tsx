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
import { AppIcon } from "@/components/ui/AppIcon";
import type {
  PriorCorrectionCandidate,
  SourceCandidate,
} from "@/api/corrections";
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

/** The acting user's own prior correction: an `as_logged` total for this portion. */
const PRIOR_CORRECTION: PriorCorrectionCandidate = {
  source_type: "prior_correction",
  source_ref: "prior_correction:abc123",
  name: "Black coffee",
  basis: "as_logged",
  calories: 3,
  protein_g: 0,
  carbs_g: 0,
  fat_g: null,
  rescaled: false,
};

type PanelProps = Partial<React.ComponentProps<typeof ChangeMatchPanel>>;

function Panel(overrides: PanelProps) {
  const { colors } = useTheme();
  return (
    <ChangeMatchPanel
      query=""
      onQueryChange={jest.fn()}
      candidates={[CANDIDATE]}
      priorCorrections={[]}
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

describe("ChangeMatchPanel prior corrections (FTY-407)", () => {
  /** Every pickable row's accessibility label, in render order. */
  function rowLabels(tree: ReactTestRenderer): string[] {
    return tree.root
      .findAll(
        (n) =>
          typeof n.props.accessibilityLabel === "string" &&
          typeof n.props.onPress === "function" &&
          String(n.props.accessibilityLabel).startsWith("Select "),
      )
      .map((n) => String(n.props.accessibilityLabel));
  }

  it("ranks the user's own correction above every guessed source match", () => {
    const tree = mount({ priorCorrections: [PRIOR_CORRECTION] });

    // Precedence mirrors FTY-406's estimate-time tier order: the user's own
    // curated value beats any re-guess.
    expect(rowLabels(tree)).toEqual([
      "Select Black coffee, your correction, 3 kcal",
      "Select Sandwich, tuna salad, 192 kcal per 100g",
    ]);
  });

  it("is pickable through the same handler as a guessed candidate", () => {
    const onPickCandidate = jest.fn();
    const tree = mount({ priorCorrections: [PRIOR_CORRECTION], onPickCandidate });

    const row = tree.root.find(
      (n) =>
        n.props.accessibilityLabel === "Select Black coffee, your correction, 3 kcal" &&
        typeof n.props.onPress === "function",
    );
    act(() => {
      row.props.onPress();
    });
    expect(onPickCandidate).toHaveBeenCalledWith(PRIOR_CORRECTION);
  });

  it("carries an always-on provenance icon for the user's own value", () => {
    const tree = mount({ priorCorrections: [PRIOR_CORRECTION] });

    const row = tree.root.find(
      (n) => n.props.accessibilityLabel === "Select Black coffee, your correction, 3 kcal",
    );
    expect(row.findAllByType(AppIcon).some((i) => i.props.name === "pencil")).toBe(true);
  });

  it("disables a prior-correction row while a re-resolve is in flight", () => {
    const tree = mount({ priorCorrections: [PRIOR_CORRECTION], reResolving: true });

    const row = tree.root.find(
      (n) => n.props.accessibilityLabel === "Select Black coffee, your correction, 3 kcal",
    );
    expect(row.props.accessibilityState).toEqual({ disabled: true });
  });

  it("shows the empty state only when neither list has anything to offer", () => {
    const empty = mount({ candidates: [], priorCorrections: [] });
    expect(
      empty.root.findAll((n) => n.props.children === "No alternatives available.").length,
    ).toBeGreaterThan(0);

    const historyOnly = mount({ candidates: [], priorCorrections: [PRIOR_CORRECTION] });
    expect(
      historyOnly.root.findAll((n) => n.props.children === "No alternatives available.").length,
    ).toBe(0);
    expect(rowLabels(historyOnly)).toEqual([
      "Select Black coffee, your correction, 3 kcal",
    ]);
  });
});
