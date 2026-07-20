/**
 * Shared fixtures and render helpers for the FTY-100 CorrectionSheet suites.
 *
 * The correction-sheet tests are split by sub-flow across sibling files
 * (`CorrectionSheet.test.tsx` plus `CorrectionSheet.<concern>.test.tsx`). The
 * item / candidate / prior-correction / props builders and the small render +
 * accessibility helpers they all lean on live here so no suite re-declares them
 * (FTY-415). Every builder and helper is a real named export imported at each
 * call site — never an implicit local shadow that could silently diverge from
 * the shared copy.
 *
 * The fixture bodies are the pre-split originals verbatim; the existing
 * `.keyboard/.rename/.exact/.accessibility` siblings keep their own local
 * copies and are intentionally left untouched.
 */

import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { ThemeProvider } from "@/theme";

import {
  type ClarificationData,
  type CorrectionSheetBaseProps,
} from "@/components/CorrectionSheet";
import type { PriorCorrectionCandidate, SourceCandidate } from "@/api/corrections";
import type { DerivedFoodItemDTO, ItemSourceDTO } from "@/api/derivedItems";
import type { SavedFoodDTO } from "@/api/savedFoods";
import type { ApiSession } from "@/state/session";
import { trackReactTestRenderer } from "@/testUtils/reactTestRenderer";
import { sourceCandidates } from "@/testUtils/correctionCandidates";

// ─── Fixtures ─────────────────────────────────────────────────────────────────

export const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "user-1",
};

function usdaSource(): ItemSourceDTO {
  return {
    source_type: "trusted_nutrition_database",
    label: "USDA",
    ref: "usda_fdc:168880",
  };
}

export function modelPriorSource(): ItemSourceDTO {
  return {
    source_type: "model_prior",
    label: "Rough estimate",
    ref: "model_prior",
  };
}

export function food(overrides: Partial<DerivedFoodItemDTO> = {}): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: "food-1",
    user_id: "user-1",
    log_event_id: "event-1",
    name: "Turkey breast",
    quantity_text: "1 serving",
    unit: "serving",
    amount: 1,
    status: "resolved",
    grams: 85,
    calories: 120,
    protein_g: 26,
    carbs_g: 0,
    fat_g: 1,
    calories_estimated: 120,
    protein_g_estimated: 26,
    carbs_g_estimated: 0,
    fat_g_estimated: 1,
    source: usdaSource(),
    is_edited: false,
    created_at: "2026-06-28T08:00:00Z",
    updated_at: "2026-06-28T08:00:00Z",
    ...overrides,
  };
}

export function candidate(overrides: Partial<SourceCandidate> = {}): SourceCandidate {
  return {
    source_type: "trusted_nutrition_database",
    source_ref: "usda_fdc:999",
    name: "Turkey breast, roasted",
    basis: "per_100g",
    calories: 135,
    protein_g: 30,
    carbs_g: 0,
    fat_g: 1.5,
    ...overrides,
  };
}

/**
 * FTY-407: the acting user's own prior correction for this item's name. Its
 * facts are the corrected **total** for the item's own portion
 * (`basis: "as_logged"`), and `fat_g` is `null` — a macro the correction never
 * supplied stays honestly unknown rather than a fabricated 0.
 */
export function priorCorrection(
  overrides: Partial<PriorCorrectionCandidate> = {},
): PriorCorrectionCandidate {
  return {
    source_type: "prior_correction",
    source_ref: "prior_correction:abc123",
    name: "Black coffee",
    basis: "as_logged",
    calories: 3,
    protein_g: 0,
    carbs_g: 0,
    fat_g: null,
    rescaled: false,
    ...overrides,
  };
}

export function savedFoodResult(): SavedFoodDTO {
  return {
    id: "saved-1",
    user_id: "user-1",
    name: "Turkey breast",
    calories: 120,
    protein_g: 26,
    carbs_g: 0,
    fat_g: 1,
    serving_size: 1,
    serving_unit: "serving",
    source: "saved_from_correction",
    created_at: "2026-06-28T10:00:00Z",
    updated_at: "2026-06-28T10:00:00Z",
  };
}

export const clarificationData: ClarificationData = {
  question: "What kind of milk?",
  options: ["Whole", "2%", "Skim", "Oat milk"],
};

// ─── Render + accessibility helpers ────────────────────────────────────────────

export function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(<ThemeProvider override="light">{element}</ThemeProvider>);
  });
  return trackReactTestRenderer(tree);
}

export function allText(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

export function allA11yLabels(tree: ReactTestRenderer): string[] {
  return tree.root
    .findAll((n) => typeof n.props.accessibilityLabel === "string")
    .map((n) => n.props.accessibilityLabel as string);
}

export function hasA11yLabel(tree: ReactTestRenderer, label: string): boolean {
  return allA11yLabels(tree).includes(label);
}

export function press(tree: ReactTestRenderer, label: string): void {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
  act(() => {
    node.props.onPress();
  });
}

export async function pressAsync(tree: ReactTestRenderer, label: string): Promise<void> {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
  await act(async () => {
    node.props.onPress();
  });
}

export function typeInto(tree: ReactTestRenderer, label: string, value: string): void {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onChangeText === "function",
  );
  act(() => {
    node.props.onChangeText(value);
  });
}

export function defaultProps(overrides: Partial<CorrectionSheetBaseProps> = {}) {
  return {
    item: food(),
    visible: true,
    onClose: jest.fn(),
    session: SESSION,
    editItem: jest.fn(),
    listCandidates: jest.fn().mockResolvedValue(sourceCandidates()),
    reResolve: jest.fn(),
    saveFood: jest.fn(),
    ...overrides,
  };
}
