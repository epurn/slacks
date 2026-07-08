import { act, create as render, type ReactTestRenderer } from "react-test-renderer";

import {
  CorrectionSheet,
  type ClarificationData,
  type CorrectionSheetBaseProps,
} from "./CorrectionSheet";
import type { DerivedFoodItemDTO, ItemSourceDTO } from "@/api/derivedItems";
import type { ApiSession } from "@/state/session";
import {
  cleanupReactTestRenderers,
  trackReactTestRenderer,
} from "@/testUtils/reactTestRenderer";
import { ThemeProvider } from "@/theme";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require("react");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { View } = require("react-native");
  return {
    SymbolView: ({ name }: { name: string }) =>
      React.createElement(View, { testID: `sf-symbol-${String(name)}` }),
  };
});

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "user-1",
};

const clarificationData: ClarificationData = {
  question: "What kind of milk?",
  options: ["Whole", "2%", "Skim", "Oat milk"],
};

function usdaSource(): ItemSourceDTO {
  return {
    source_type: "trusted_nutrition_database",
    label: "USDA",
    ref: "usda_fdc:168880",
  };
}

function food(overrides: Partial<DerivedFoodItemDTO> = {}): DerivedFoodItemDTO {
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

function defaultProps(overrides: Partial<CorrectionSheetBaseProps> = {}) {
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

function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(<ThemeProvider override="light">{element}</ThemeProvider>);
  });
  return trackReactTestRenderer(tree);
}

function allText(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

beforeEach(() => mockReduceMotion(false));
afterEach(() => {
  cleanupReactTestRenderers();
  jest.restoreAllMocks();
});

describe("CorrectionSheet accessibility details", () => {
  it("renders the full logged phrase in clarify mode without truncating it", () => {
    const longPhrase =
      "a large bowl of homemade granola with milk, blueberries, and honey drizzled on top";
    const tree = mount(
      <CorrectionSheet
        {...defaultProps()}
        logPhrase={longPhrase}
        needsClarification
        clarificationData={clarificationData}
      />,
    );
    const phrase = tree.root.findByProps({ testID: "clarify-full-phrase" });
    expect(phrase.props.children).toBe(longPhrase);
    expect(phrase.props.numberOfLines).toBeUndefined();
    expect(allText(tree)).toContain(longPhrase);
  });

  it("delegates present/dismiss motion to the native sheet (honours Reduce Motion)", async () => {
    // The old hand-faked Modal switched its own animationType off Reduce Motion.
    // The native sheet's presentation controller honours Reduce Motion itself, so
    // there is no JS animation flag to toggle — the sheet renders the same under
    // either setting, and the motion is the system's to reduce.
    mockReduceMotion(true);
    let tree!: ReactTestRenderer;
    await act(async () => {
      tree = render(
        <ThemeProvider override="light">
          <CorrectionSheet {...defaultProps()} />
        </ThemeProvider>,
      );
    });
    await act(async () => {});
    expect(allText(tree)).toContain("Turkey breast");
  });
});
