/**
 * Tests for the FTY-197 ConfirmParsedValuesSheet.
 *
 * The confirm-parsed-values sheet shows an uncounted label parse (FTY-196
 * `proposed` item) for confirm/adjust before it counts. All API calls are mocked
 * (the FTY-196 confirm action). Coverage mirrors the story's Verification:
 *   - Shows the parse: parsed values + "Label scan" provenance + not-yet-counted.
 *   - Confirm counts: "Looks right" calls confirm with an empty (unchanged) body.
 *   - Adjust: editing a value then confirming sends the adjusted value.
 *   - Never silent: no confirm call fires without an explicit action; a dismiss
 *     leaves the proposal uncounted (onConfirmed never fires).
 *   - Accessibility: value / not-yet-counted state / confirm+adjust affordances
 *     are exposed to VoiceOver; ≥44pt targets.
 */

import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { DISPLAY_FONT_FAMILY, ThemeProvider, typeScale } from "@/theme";

import { ConfirmParsedValuesSheet } from "./ConfirmParsedValuesSheet";
import {
  type DerivedFoodItemDTO,
  type ItemSourceDTO,
} from "@/api/derivedItems";
import { LabelProposalApiError } from "@/api/labelProposal";
import type { ApiSession } from "@/state/session";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

// expo-symbols is a native module — stub SymbolView so the provenance icon
// renders (same pattern as CorrectionSheet.test.tsx / AppIcon.test.tsx).
jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require("react");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require("react-native");
  return {
    SymbolView: ({
      name,
      accessibilityLabel,
    }: {
      name: string;
      accessibilityLabel?: string;
    }) =>
      React.createElement(View, {
        testID: `sf-symbol-${String(name)}`,
        accessibilityLabel,
      }),
  };
});

// ─── Fixtures ─────────────────────────────────────────────────────────────────

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "user-1",
};

function labelSource(): ItemSourceDTO {
  return { source_type: "user_label", label: "Label scan", ref: "user_label" };
}

/** A legible label parse held `proposed` (uncounted) — the FTY-196 read shape. */
function proposal(overrides: Partial<DerivedFoodItemDTO> = {}): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: "food-1",
    user_id: "user-1",
    log_event_id: "event-1",
    name: "Granola bar",
    quantity_text: "1 serving",
    unit: "bar",
    amount: 1,
    status: "proposed",
    grams: 40,
    calories: 190,
    protein_g: 4,
    carbs_g: 29,
    fat_g: 7,
    calories_estimated: 190,
    protein_g_estimated: 4,
    carbs_g_estimated: 29,
    fat_g_estimated: 7,
    source: labelSource(),
    is_edited: false,
    created_at: "2026-07-02T08:00:00Z",
    updated_at: "2026-07-02T08:00:00Z",
    ...overrides,
  };
}

// ─── Test helpers ──────────────────────────────────────────────────────────────

function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(<ThemeProvider override="light">{element}</ThemeProvider>);
  });
  return tree;
}

function allText(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

function allA11yLabels(tree: ReactTestRenderer): string[] {
  return tree.root
    .findAll((n) => typeof n.props.accessibilityLabel === "string")
    .map((n) => n.props.accessibilityLabel as string);
}

function findByLabel(tree: ReactTestRenderer, label: string) {
  return tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
}

async function pressAsync(tree: ReactTestRenderer, label: string): Promise<void> {
  const node = findByLabel(tree, label);
  await act(async () => {
    node.props.onPress();
  });
}

function press(tree: ReactTestRenderer, label: string): void {
  const node = findByLabel(tree, label);
  act(() => {
    node.props.onPress();
  });
}

function typeInto(tree: ReactTestRenderer, label: string, value: string): void {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onChangeText === "function",
  );
  act(() => {
    node.props.onChangeText(value);
  });
}

function defaultProps(overrides: Record<string, unknown> = {}) {
  return {
    item: proposal(),
    visible: true,
    session: SESSION,
    onClose: jest.fn(),
    onConfirmed: jest.fn(),
    confirm: jest.fn().mockResolvedValue(proposal({ status: "resolved" })),
    ...overrides,
  };
}

beforeEach(() => {
  mockReduceMotion(false);
});

// ─── Shows the parse ────────────────────────────────────────────────────────────

describe("ConfirmParsedValuesSheet — shows the parse", () => {
  it("renders the parsed calories, macros, serving, and Label scan provenance", () => {
    const tree = mount(<ConfirmParsedValuesSheet {...defaultProps()} />);
    const text = allText(tree);
    expect(text).toContain("Granola bar");
    expect(text).toContain("190 kcal");
    expect(text).toContain("Label scan");
    // macros are shown
    expect(text).toContain("29g");
  });

  it("renders the calorie hero numeral through DisplayText", () => {
    const tree = mount(<ConfirmParsedValuesSheet {...defaultProps()} />);
    const heroNumber = tree.root.find(
      (n) =>
        (n.type as unknown as string) === "Text" && n.props.children === "190 kcal",
    );
    const style: Record<string, unknown> = Object.assign(
      {},
      ...(Array.isArray(heroNumber.props.style) ? heroNumber.props.style : [heroNumber.props.style]),
    );
    expect(style.fontFamily).toBe(DISPLAY_FONT_FAMILY);
    expect(style.fontSize).toBe(typeScale.title2);
    expect(style.fontVariant).toEqual(["tabular-nums"]);
  });

  it("marks the entry not yet counted", () => {
    const tree = mount(<ConfirmParsedValuesSheet {...defaultProps()} />);
    expect(allText(tree)).toContain("Not yet counted");
    // VoiceOver conveys the not-yet-counted state on the values summary.
    expect(
      allA11yLabels(tree).some((l) => l.includes("not yet counted")),
    ).toBe(true);
  });

  it("does not confirm on mount — no auto-confirm", () => {
    const confirm = jest.fn().mockResolvedValue(proposal({ status: "resolved" }));
    const onConfirmed = jest.fn();
    mount(
      <ConfirmParsedValuesSheet
        {...defaultProps({ confirm, onConfirmed })}
      />,
    );
    expect(confirm).not.toHaveBeenCalled();
    expect(onConfirmed).not.toHaveBeenCalled();
  });
});

// ─── Confirm counts ─────────────────────────────────────────────────────────────

describe("ConfirmParsedValuesSheet — confirm", () => {
  it("Looks right calls confirm with an empty body (parse unchanged) and reports the committed item", async () => {
    const committed = proposal({ status: "resolved" });
    const confirm = jest.fn().mockResolvedValue(committed);
    const onConfirmed = jest.fn();
    const tree = mount(
      <ConfirmParsedValuesSheet {...defaultProps({ confirm, onConfirmed })} />,
    );

    await pressAsync(tree, "Looks right, add it");

    expect(confirm).toHaveBeenCalledTimes(1);
    expect(confirm).toHaveBeenCalledWith(SESSION, "event-1", {});
    expect(onConfirmed).toHaveBeenCalledWith(committed);
  });

  it("surfaces a confirm failure without reporting a commit", async () => {
    const confirm = jest
      .fn()
      .mockRejectedValue(new LabelProposalApiError(404, "We couldn't find that label entry."));
    const onConfirmed = jest.fn();
    const tree = mount(
      <ConfirmParsedValuesSheet {...defaultProps({ confirm, onConfirmed })} />,
    );

    await pressAsync(tree, "Looks right, add it");

    expect(onConfirmed).not.toHaveBeenCalled();
    expect(allText(tree)).toContain("We couldn't find that label entry.");
  });
});

// ─── Adjust ──────────────────────────────────────────────────────────────────

describe("ConfirmParsedValuesSheet — adjust", () => {
  it("editing a value then confirming sends only the changed field", async () => {
    const confirm = jest.fn().mockResolvedValue(proposal({ status: "resolved" }));
    const tree = mount(<ConfirmParsedValuesSheet {...defaultProps({ confirm })} />);

    press(tree, "Adjust values");
    typeInto(tree, "Calories value", "250");
    await pressAsync(tree, "Add adjusted values");

    expect(confirm).toHaveBeenCalledTimes(1);
    expect(confirm).toHaveBeenCalledWith(SESSION, "event-1", { calories: 250 });
  });

  it("an unchanged adjust confirm sends an empty body (keeps the parse un-edited)", async () => {
    const confirm = jest.fn().mockResolvedValue(proposal({ status: "resolved" }));
    const tree = mount(<ConfirmParsedValuesSheet {...defaultProps({ confirm })} />);

    press(tree, "Adjust values");
    await pressAsync(tree, "Add adjusted values");

    expect(confirm).toHaveBeenCalledWith(SESSION, "event-1", {});
  });

  it("increasing servings sends the adjusted amount as a rescale", async () => {
    const confirm = jest.fn().mockResolvedValue(proposal({ status: "resolved" }));
    const tree = mount(<ConfirmParsedValuesSheet {...defaultProps({ confirm })} />);

    press(tree, "Adjust values");
    press(tree, "Increase servings"); // 1 → 1.25
    await pressAsync(tree, "Add adjusted values");

    expect(confirm).toHaveBeenCalledWith(SESSION, "event-1", { amount: 1.25 });
  });
});

// ─── Never silent ──────────────────────────────────────────────────────────────

describe("ConfirmParsedValuesSheet — never silently counts", () => {
  it("dismissing without confirming leaves the proposal uncounted", () => {
    const confirm = jest.fn();
    const onConfirmed = jest.fn();
    const onClose = jest.fn();
    const tree = mount(
      <ConfirmParsedValuesSheet
        {...defaultProps({ confirm, onConfirmed, onClose })}
      />,
    );

    press(tree, "Close");

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(confirm).not.toHaveBeenCalled();
    expect(onConfirmed).not.toHaveBeenCalled();
  });
});

// ─── Accessibility ──────────────────────────────────────────────────────────────

describe("ConfirmParsedValuesSheet — accessibility", () => {
  it("exposes the confirm and adjust affordances to VoiceOver", () => {
    const tree = mount(<ConfirmParsedValuesSheet {...defaultProps()} />);
    const labels = allA11yLabels(tree);
    expect(labels).toContain("Looks right, add it");
    expect(labels).toContain("Adjust values");
    expect(labels).toContain("Close");
  });

  it("gives the primary and secondary buttons ≥44pt targets", () => {
    const tree = mount(<ConfirmParsedValuesSheet {...defaultProps()} />);
    for (const label of ["Looks right, add it", "Adjust values"]) {
      const node = findByLabel(tree, label);
      const style = Array.isArray(node.props.style)
        ? Object.assign({}, ...node.props.style.filter(Boolean))
        : node.props.style;
      expect(style.height).toBeGreaterThanOrEqual(44);
    }
  });
});
