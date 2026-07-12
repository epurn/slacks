/**
 * FTY-312: `Make it exact` exact-evidence flow in the correction sheet.
 *
 * All FTY-310 exact-evidence clients and the FTY-311 capture surfaces are mocked;
 * the sheet is presented standalone. Coverage mirrors the story Verification:
 *   - eligibility / hiding by source type and food/exercise item type;
 *   - choice surface opens from `Make it exact` (not Change match);
 *   - typed barcode exact proposal preview;
 *   - typed barcode fallback proposal preview + fallback copy marker;
 *   - no-proposal / API-error states leave the item unchanged;
 *   - scanned barcode calls the proposal API (no new log event);
 *   - label capture calls the label proposal API with the save flag;
 *   - apply sends proposal ref + amount only, updates local/parent item, beats;
 *   - accessibility labels on entry, choices, exact/fallback, amount, actions.
 */

import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

import { ThemeProvider } from "@/theme";

import { CorrectionSheet, type CorrectionSheetBaseProps } from "./CorrectionSheet";
import { BarcodeScannerScreen } from "./BarcodeScannerScreen";
import { LabelCaptureScreen } from "./LabelCaptureScreen";
import {
  ExactEvidenceApiError,
  type ExactEvidenceProposal,
  type ExactEvidenceProposalPreview,
} from "@/api/exactEvidence";
import {
  type DerivedExerciseItemDTO,
  type DerivedFoodItemDTO,
  type ItemSourceDTO,
} from "@/api/derivedItems";
import type { ApiSession } from "@/state/session";
import { cleanupReactTestRenderers, trackReactTestRenderer } from "@/testUtils/reactTestRenderer";
import { mockReduceMotion } from "@/testUtils/reduceMotion";
import { correctionSavedHaptic } from "@/theme/haptics";

jest.mock("@/theme/haptics", () => ({
  correctionSavedHaptic: jest.fn(),
  entryResolvedHaptic: jest.fn(),
  targetReachedHaptic: jest.fn(),
}));

const mockCorrectionSavedHaptic = correctionSavedHaptic as jest.MockedFunction<
  typeof correctionSavedHaptic
>;

// expo-camera: granted permissions + a CameraView stub, so the FTY-311 capture
// surfaces render inside their modals without a real camera.
jest.mock("expo-camera", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require("react-native");
  return {
    useCameraPermissions: jest.fn(() => [
      { status: "granted", granted: true, canAskAgain: false, expires: "never" },
      jest.fn().mockResolvedValue({ status: "granted", granted: true }),
      jest.fn().mockResolvedValue({ status: "granted", granted: true }),
    ]),
    CameraView: jest.fn().mockImplementation((props: Record<string, unknown>) =>
      ReactLib.createElement(View, { ...props, testID: "camera-view" }),
    ),
  };
});

jest.mock("expo-linking", () => ({
  openSettings: jest.fn().mockResolvedValue(undefined),
}));

// expo-symbols is native — stub SymbolView (same pattern as the sibling tests).
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

function source(source_type: ItemSourceDTO["source_type"], label = "src"): ItemSourceDTO {
  return { source_type, label, ref: `${source_type}:1` };
}

function food(overrides: Partial<DerivedFoodItemDTO> = {}): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: "food-1",
    user_id: "user-1",
    log_event_id: "event-1",
    name: "Granola bar",
    quantity_text: "1 serving",
    unit: "serving",
    amount: 1,
    status: "resolved",
    grams: 40,
    calories: 150,
    protein_g: 4,
    carbs_g: 22,
    fat_g: 6,
    calories_estimated: 150,
    protein_g_estimated: 4,
    carbs_g_estimated: 22,
    fat_g_estimated: 6,
    source: source("model_prior", "Rough estimate"),
    is_edited: false,
    created_at: "2026-07-01T08:00:00Z",
    updated_at: "2026-07-01T08:00:00Z",
    ...overrides,
  };
}

function exercise(): DerivedExerciseItemDTO {
  return {
    item_type: "exercise",
    id: "ex-1",
    user_id: "user-1",
    log_event_id: "event-2",
    name: "Running",
    quantity_text: "30 min",
    unit: "min",
    amount: 30,
    status: "resolved",
    active_calories: 300,
    active_calories_estimated: 300,
    source: null,
    is_edited: false,
    created_at: "2026-07-01T08:00:00Z",
    updated_at: "2026-07-01T08:00:00Z",
  };
}

function preview(
  overrides: Partial<ExactEvidenceProposalPreview> = {},
): ExactEvidenceProposalPreview {
  return {
    source: source("product_database", "Open Food Facts"),
    calories: 200,
    protein_g: 10,
    carbs_g: 20,
    fat_g: 5,
    amount: 1,
    serving_label: "1 bar (40 g)",
    ...overrides,
  };
}

function exactProposal(overrides: Partial<ExactEvidenceProposal> = {}): ExactEvidenceProposal {
  return {
    proposal_ref: "ref-exact",
    kind: "barcode",
    can_cost_current_amount: true,
    quality: "exact",
    failure_reason: null,
    preview: preview(),
    ...overrides,
  } as ExactEvidenceProposal;
}

function fallbackProposal(): ExactEvidenceProposal {
  return {
    proposal_ref: "ref-fallback",
    kind: "barcode",
    can_cost_current_amount: true,
    quality: "fallback",
    failure_reason: "barcode_no_match",
    preview: preview({ source: source("model_prior", "Rough estimate") }),
  } as ExactEvidenceProposal;
}

function noneProposal(): ExactEvidenceProposal {
  return {
    proposal_ref: "ref-none",
    kind: "barcode",
    can_cost_current_amount: true,
    quality: "none",
    failure_reason: "no_usable_facts",
    preview: null,
  } as ExactEvidenceProposal;
}

// ─── Test helpers ──────────────────────────────────────────────────────────────

const INITIAL_METRICS = {
  frame: { x: 0, y: 0, width: 390, height: 844 },
  insets: { top: 47, left: 0, right: 0, bottom: 34 },
};

function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(
      <SafeAreaProvider initialMetrics={INITIAL_METRICS}>
        <ThemeProvider override="light">{element}</ThemeProvider>
      </SafeAreaProvider>,
    );
  });
  return trackReactTestRenderer(tree);
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

function hasA11yLabel(tree: ReactTestRenderer, label: string): boolean {
  return allA11yLabels(tree).includes(label);
}

/** Whether the pressable with this accessibility label reports itself disabled. */
function a11yDisabled(tree: ReactTestRenderer, label: string): boolean {
  const node = tree.root.find(
    (n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function",
  );
  return node.props.accessibilityState?.disabled === true;
}

async function press(tree: ReactTestRenderer, label: string): Promise<void> {
  const node = tree.root.find(
    (n) => n.props.accessibilityLabel === label && typeof n.props.onPress === "function",
  );
  await act(async () => {
    node.props.onPress();
  });
}

function type(tree: ReactTestRenderer, label: string, value: string): void {
  const node = tree.root.find(
    (n) => n.props.accessibilityLabel === label && typeof n.props.onChangeText === "function",
  );
  act(() => {
    node.props.onChangeText(value);
  });
}

function defaultProps(
  overrides: Partial<CorrectionSheetBaseProps> = {},
): CorrectionSheetBaseProps {
  return {
    item: food(),
    visible: true,
    onClose: jest.fn(),
    session: SESSION,
    editItem: jest.fn(),
    listCandidates: jest.fn().mockResolvedValue([]),
    reResolve: jest.fn(),
    saveFood: jest.fn(),
    ...overrides,
  };
}

/** Drive the sheet into the exact-evidence preview via a typed barcode. */
async function toTypedPreview(
  tree: ReactTestRenderer,
  barcode = "0123456789012",
): Promise<void> {
  await press(tree, "Make it exact");
  await press(tree, "Type barcode");
  type(tree, "Barcode", barcode);
  await press(tree, "Look up barcode");
}

beforeEach(() => {
  mockReduceMotion(false);
  mockCorrectionSavedHaptic.mockClear();
});

afterEach(() => {
  cleanupReactTestRenderers();
  jest.restoreAllMocks();
});

// ─── Eligibility ────────────────────────────────────────────────────────────

describe("Make it exact eligibility", () => {
  it.each([
    ["model_prior", source("model_prior", "Rough estimate"), {}],
    ["reference_source", source("reference_source", "Reference"), {}],
    ["user_text macros missing", source("user_text", "You said"), { protein_g: null }],
    [
      "user_text with estimate_basis",
      { ...source("user_text", "You said"), estimate_basis: "comparable_reference" as const },
      {},
    ],
  ])("shows the nudge for a low-trust/incomplete food item (%s)", async (_name, src, extra) => {
    const tree = mount(
      <CorrectionSheet {...defaultProps({ item: food({ source: src, ...extra }) })} />,
    );
    expect(hasA11yLabel(tree, "Make it exact")).toBe(true);
  });

  it.each([
    ["user_label", source("user_label", "Label scan")],
    ["product_database", source("product_database", "Open Food Facts")],
    ["trusted_nutrition_database", source("trusted_nutrition_database", "USDA")],
    ["official_source", source("official_source", "Reference")],
  ])("hides the nudge for a trusted food source (%s)", (_name, src) => {
    const tree = mount(<CorrectionSheet {...defaultProps({ item: food({ source: src }) })} />);
    expect(hasA11yLabel(tree, "Make it exact")).toBe(false);
    // The normal Change match lever is preserved.
    expect(hasA11yLabel(tree, "Change match")).toBe(true);
  });

  it("hides the nudge for a fully-specified user_text item", () => {
    const tree = mount(
      <CorrectionSheet {...defaultProps({ item: food({ source: source("user_text", "You said") }) })} />,
    );
    expect(hasA11yLabel(tree, "Make it exact")).toBe(false);
  });

  it("hides the nudge for an exercise item and does not crash", () => {
    const tree = mount(<CorrectionSheet {...defaultProps({ item: exercise() })} />);
    expect(hasA11yLabel(tree, "Make it exact")).toBe(false);
  });
});

// ─── Choice surface ───────────────────────────────────────────────────────────

describe("choice surface", () => {
  it("opens a dedicated barcode/label choice surface from Make it exact", async () => {
    const tree = mount(<CorrectionSheet {...defaultProps()} />);
    await press(tree, "Make it exact");
    expect(hasA11yLabel(tree, "Scan barcode")).toBe(true);
    expect(hasA11yLabel(tree, "Type barcode")).toBe(true);
    expect(hasA11yLabel(tree, "Capture nutrition label")).toBe(true);
    expect(hasA11yLabel(tree, "Cancel make it exact")).toBe(true);
    // The amount stepper / change-match levers are replaced while active.
    expect(hasA11yLabel(tree, "Change match")).toBe(false);
  });

  it("Cancel returns to the normal sheet levers", async () => {
    const tree = mount(<CorrectionSheet {...defaultProps()} />);
    await press(tree, "Make it exact");
    await press(tree, "Cancel make it exact");
    expect(hasA11yLabel(tree, "Change match")).toBe(true);
    expect(hasA11yLabel(tree, "Scan barcode")).toBe(false);
  });
});

// ─── Typed barcode ────────────────────────────────────────────────────────────

describe("typed barcode", () => {
  it("requests a proposal and renders the exact preview", async () => {
    const requestBarcodeProposal = jest.fn().mockResolvedValue(exactProposal());
    const tree = mount(<CorrectionSheet {...defaultProps({ requestBarcodeProposal })} />);
    await toTypedPreview(tree);
    expect(requestBarcodeProposal).toHaveBeenCalledWith(SESSION, "food-1", "0123456789012");
    // Exact state marker + proposed values.
    expect(allText(tree)).toContain("Exact match · Open Food Facts");
    expect(allText(tree)).toContain("200 kcal");
    expect(hasA11yLabel(tree, "Apply")).toBe(true);
  });

  it("shows a loading state while the proposal request is in flight", async () => {
    let resolveProposal!: (p: ExactEvidenceProposal) => void;
    const requestBarcodeProposal = jest
      .fn()
      .mockReturnValue(new Promise<ExactEvidenceProposal>((r) => (resolveProposal = r)));
    const tree = mount(<CorrectionSheet {...defaultProps({ requestBarcodeProposal })} />);
    await press(tree, "Make it exact");
    await press(tree, "Type barcode");
    type(tree, "Barcode", "0123456789012");
    await press(tree, "Look up barcode");
    expect(hasA11yLabel(tree, "Looking up exact evidence")).toBe(true);
    await act(async () => {
      resolveProposal(exactProposal());
    });
    expect(hasA11yLabel(tree, "Apply")).toBe(true);
  });

  it("renders the fallback preview with honest fallback copy, never labelled exact", async () => {
    const requestBarcodeProposal = jest.fn().mockResolvedValue(fallbackProposal());
    const tree = mount(<CorrectionSheet {...defaultProps({ requestBarcodeProposal })} />);
    await toTypedPreview(tree);
    expect(allText(tree)).toContain(
      "No exact match from that barcode. This is the best rough fallback.",
    );
    expect(allText(tree)).toContain("Rough fallback");
    expect(allText(tree)).not.toContain("Exact match");
    // Still applyable.
    expect(hasA11yLabel(tree, "Apply")).toBe(true);
  });

  it("empty barcode shows an inline nudge and makes no request", async () => {
    const requestBarcodeProposal = jest.fn();
    const tree = mount(<CorrectionSheet {...defaultProps({ requestBarcodeProposal })} />);
    await press(tree, "Make it exact");
    await press(tree, "Type barcode");
    await press(tree, "Look up barcode");
    expect(requestBarcodeProposal).not.toHaveBeenCalled();
    expect(allText(tree)).toContain("Enter a barcode to look up.");
  });

  it("a no-proposal result shows a calm error and leaves the item unchanged", async () => {
    const requestBarcodeProposal = jest.fn().mockResolvedValue(noneProposal());
    const onItemChange = jest.fn();
    const tree = mount(
      <CorrectionSheet {...defaultProps({ requestBarcodeProposal, onItemChange })} />,
    );
    await toTypedPreview(tree);
    expect(onItemChange).not.toHaveBeenCalled();
    expect(hasA11yLabel(tree, "Apply")).toBe(false);
    // A path back is always offered.
    expect(hasA11yLabel(tree, "Try again")).toBe(true);
    expect(hasA11yLabel(tree, "Change match")).toBe(true);
    expect(hasA11yLabel(tree, "Manual edit")).toBe(true);
  });

  it("an API failure shows a content-free error and leaves the item unchanged", async () => {
    const requestBarcodeProposal = jest
      .fn()
      .mockRejectedValue(new ExactEvidenceApiError(503, "That's temporarily unavailable. Please try again in a moment."));
    const onItemChange = jest.fn();
    const tree = mount(
      <CorrectionSheet {...defaultProps({ requestBarcodeProposal, onItemChange })} />,
    );
    await toTypedPreview(tree);
    expect(onItemChange).not.toHaveBeenCalled();
    expect(allText(tree)).toContain("temporarily unavailable");
    expect(hasA11yLabel(tree, "Try again")).toBe(true);
  });
});

// ─── Scanned barcode + label capture (FTY-311 adapters) ──────────────────────

describe("capture adapters", () => {
  it("a scanned barcode calls the proposal API (no new log event)", async () => {
    const requestBarcodeProposal = jest.fn().mockResolvedValue(exactProposal());
    const tree = mount(<CorrectionSheet {...defaultProps({ requestBarcodeProposal })} />);
    await press(tree, "Make it exact");
    await press(tree, "Scan barcode");
    const scanner = tree.root.findByType(BarcodeScannerScreen);
    // The scanner is a pure barcode source — no onManualEntry composer fallback.
    expect(scanner.props.onManualEntry).toBeUndefined();
    await act(async () => {
      scanner.props.onBarcodeScanned("9990000000001");
    });
    expect(requestBarcodeProposal).toHaveBeenCalledWith(SESSION, "food-1", "9990000000001");
    expect(allText(tree)).toContain("Exact match · Open Food Facts");
  });

  it("label capture calls the label proposal API with the save flag", async () => {
    const uploadLabelProposal = jest.fn().mockResolvedValue(exactProposal({ kind: "label" }));
    const tree = mount(<CorrectionSheet {...defaultProps({ uploadLabelProposal })} />);
    await press(tree, "Make it exact");
    await press(tree, "Capture nutrition label");
    const capture = tree.root.findByType(LabelCaptureScreen);
    await act(async () => {
      await capture.props.onSubmit({ imageUri: "file://label.jpg", savePhoto: true });
    });
    expect(uploadLabelProposal).toHaveBeenCalledWith(
      SESSION,
      "food-1",
      "file://label.jpg",
      true,
    );
  });
});

// ─── Apply ────────────────────────────────────────────────────────────────────

describe("apply", () => {
  it("applies with only the proposal ref when the amount is unchanged", async () => {
    const applied = food({ source: source("product_database", "Open Food Facts"), calories: 200 });
    const requestBarcodeProposal = jest.fn().mockResolvedValue(exactProposal());
    const applyProposal = jest.fn().mockResolvedValue(applied);
    const onItemChange = jest.fn();
    const tree = mount(
      <CorrectionSheet
        {...defaultProps({ requestBarcodeProposal, applyProposal, onItemChange })}
      />,
    );
    await toTypedPreview(tree);
    await press(tree, "Apply");
    // No amount sent — the ref alone (no calories/macros ever leave the client).
    expect(applyProposal).toHaveBeenCalledWith(SESSION, "food-1", "ref-exact", undefined);
    expect(onItemChange).toHaveBeenCalledWith(applied);
    expect(mockCorrectionSavedHaptic).toHaveBeenCalledTimes(1);
    // Back in the normal sheet with the new source visible.
    expect(hasA11yLabel(tree, "Change match")).toBe(true);
  });

  it("sends the adjusted amount only when the user changes it", async () => {
    const requestBarcodeProposal = jest.fn().mockResolvedValue(exactProposal());
    const applyProposal = jest.fn().mockResolvedValue(food({ calories: 250 }));
    const tree = mount(
      <CorrectionSheet {...defaultProps({ requestBarcodeProposal, applyProposal })} />,
    );
    await toTypedPreview(tree);
    await press(tree, "Increase amount"); // 1 → 1.25
    await press(tree, "Apply");
    expect(applyProposal).toHaveBeenCalledWith(SESSION, "food-1", "ref-exact", 1.25);
  });

  it("never sends a guessed amount when the preview basis differs from the item", async () => {
    // Costable proposal whose preview basis (2) differs from the item amount (1):
    // an untouched Apply must preserve the current portion, not the preview's.
    const requestBarcodeProposal = jest
      .fn()
      .mockResolvedValue(exactProposal({ preview: preview({ amount: 2 }) }));
    const applyProposal = jest.fn().mockResolvedValue(food({ calories: 200 }));
    const tree = mount(
      <CorrectionSheet {...defaultProps({ requestBarcodeProposal, applyProposal })} />,
    );
    await toTypedPreview(tree);
    await press(tree, "Apply");
    expect(applyProposal).toHaveBeenCalledWith(SESSION, "food-1", "ref-exact", undefined);
  });

  it("blocks Apply on an uncostable proposal until the user sets an explicit amount", async () => {
    // can_cost_current_amount=false: preserving the current portion is impossible,
    // so the client must ask for an explicit amount rather than guessing one.
    const requestBarcodeProposal = jest
      .fn()
      .mockResolvedValue(exactProposal({ can_cost_current_amount: false }));
    const applyProposal = jest.fn().mockResolvedValue(food({ calories: 200 }));
    const tree = mount(
      <CorrectionSheet {...defaultProps({ requestBarcodeProposal, applyProposal })} />,
    );
    await toTypedPreview(tree);
    // Apply is disabled and pressing it never manufactures an amount.
    expect(a11yDisabled(tree, "Apply")).toBe(true);
    await press(tree, "Apply");
    expect(applyProposal).not.toHaveBeenCalled();
    // Once the user sets an explicit amount, apply carries exactly that amount.
    await press(tree, "Increase amount"); // 1 → 1.25
    expect(a11yDisabled(tree, "Apply")).toBe(false);
    await press(tree, "Apply");
    expect(applyProposal).toHaveBeenCalledWith(SESSION, "food-1", "ref-exact", 1.25);
  });
});

// ─── Accessibility ────────────────────────────────────────────────────────────

describe("accessibility", () => {
  it("labels the entry point, choices, exact state, amount, and actions", async () => {
    const requestBarcodeProposal = jest.fn().mockResolvedValue(exactProposal());
    const tree = mount(<CorrectionSheet {...defaultProps({ requestBarcodeProposal })} />);
    expect(hasA11yLabel(tree, "Make it exact")).toBe(true);
    await press(tree, "Make it exact");
    for (const label of ["Scan barcode", "Type barcode", "Capture nutrition label", "Cancel make it exact"]) {
      expect(hasA11yLabel(tree, label)).toBe(true);
    }
    await toTypedPreview(tree);
    for (const label of ["Apply", "Try again", "Change match", "Manual edit", "Increase amount", "Decrease amount"]) {
      expect(hasA11yLabel(tree, label)).toBe(true);
    }
    // The exact state carries a VoiceOver label.
    expect(allA11yLabels(tree).some((l) => l.startsWith("Exact match from"))).toBe(true);
  });
});
