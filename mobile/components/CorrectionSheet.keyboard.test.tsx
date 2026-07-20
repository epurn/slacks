/**
 * FTY-404: keyboard-avoidance for the correction sheet.
 *
 * A focused correction field raises the software keyboard; without avoidance it
 * covers the Save action and the match/typeahead list at the bottom of the
 * sheet. These tests prove that while the keyboard-avoiding container reports an
 * inset, the scroll content is padded by the real keyboard height, the Save
 * control and the match list stay present/reachable, and the bottom-anchored
 * override action is scrolled clear of the keyboard.
 */

import { Keyboard, ScrollView } from "react-native";
import { act, create as render, type ReactTestRenderer } from "react-test-renderer";

import { ThemeProvider } from "@/theme";

import { CorrectionSheet, type CorrectionSheetBaseProps } from "./CorrectionSheet";
import { ChangeMatchPanel } from "./correction/ChangeMatchPanel";
import type { SourceCandidate } from "@/api/corrections";
import type { DerivedFoodItemDTO, ItemSourceDTO } from "@/api/derivedItems";
import type { ApiSession } from "@/state/session";
import { cleanupReactTestRenderers, trackReactTestRenderer } from "@/testUtils/reactTestRenderer";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

jest.mock("@/theme/haptics", () => ({
  correctionSavedHaptic: jest.fn(),
  entryResolvedHaptic: jest.fn(),
  targetReachedHaptic: jest.fn(),
}));

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

function candidate(overrides: Partial<SourceCandidate> = {}): SourceCandidate {
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

function baseProps(overrides: Partial<CorrectionSheetBaseProps> = {}): CorrectionSheetBaseProps {
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

// Capture the `Keyboard` subscriptions the sheet's `useKeyboardInset` registers
// so a synthetic show event can drive the container's reported inset.
type Handler = (event: { endCoordinates?: { height: number } }) => void;
let keyboardSubs: Array<{ event: string; cb: Handler }>;

beforeEach(() => {
  mockReduceMotion(false);
  keyboardSubs = [];
  jest
    .spyOn(Keyboard, "addListener")
    .mockImplementation((event: string, cb: unknown) => {
      keyboardSubs.push({ event, cb: cb as Handler });
      return { remove: jest.fn() } as never;
    });
  // Run rAF callbacks synchronously so the scroll-to-end effect is observable.
  jest
    .spyOn(globalThis, "requestAnimationFrame")
    .mockImplementation((cb: FrameRequestCallback) => {
      cb(0);
      return 0;
    });
  jest.spyOn(globalThis, "cancelAnimationFrame").mockImplementation(() => {});
});

afterEach(() => {
  cleanupReactTestRenderers();
  jest.restoreAllMocks();
});

async function mount(element: React.ReactElement): Promise<ReactTestRenderer> {
  let tree!: ReactTestRenderer;
  await act(async () => {
    tree = render(<ThemeProvider override="light">{element}</ThemeProvider>);
  });
  return trackReactTestRenderer(tree);
}

function scrollView(tree: ReactTestRenderer) {
  return tree.root.findByType(ScrollView);
}

function contentPaddingBottom(tree: ReactTestRenderer): number {
  const style = scrollView(tree).props.contentContainerStyle as unknown[];
  return style
    .filter((s): s is { paddingBottom?: number } => s != null && typeof s === "object")
    .reduce((acc, s) => (typeof s.paddingBottom === "number" ? s.paddingBottom : acc), 0);
}

function showKeyboard(height = 291): void {
  const show = keyboardSubs.find((s) => /Show|ChangeFrame/.test(s.event));
  act(() => {
    show?.cb({ endCoordinates: { height } });
  });
}

function texts(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

function hasA11yLabel(tree: ReactTestRenderer, label: string): boolean {
  return tree.root.findAll((n) => n.props.accessibilityLabel === label).length > 0;
}

describe("CorrectionSheet keyboard-avoidance", () => {
  it("configures the scroll container for keyboard-avoidance", async () => {
    const tree = await mount(<CorrectionSheet {...baseProps()} />);
    const sv = scrollView(tree);
    expect(sv.props.keyboardShouldPersistTaps).toBe("handled");
    expect(sv.props.keyboardDismissMode).toBe("interactive");
  });

  it("pads the scroll content by the live keyboard height so controls clear the keyboard", async () => {
    const tree = await mount(<CorrectionSheet {...baseProps()} e2eInitialMode="override" />);
    const restingPadding = contentPaddingBottom(tree);

    showKeyboard(291);

    // The keyboard's real height is added to the resting bottom padding — the
    // platform inset, no magic offset.
    expect(contentPaddingBottom(tree)).toBe(restingPadding + 291);
  });

  it("keeps the match/typeahead list present while the keyboard reports an inset", async () => {
    const listCandidates = jest.fn().mockResolvedValue([
      candidate({ name: "Turkey breast, roasted" }),
      candidate({ name: "Turkey breast, raw", source_ref: "usda_fdc:888" }),
    ]);
    const tree = await mount(
      <CorrectionSheet {...baseProps({ listCandidates })} e2eInitialMode="change-match" />,
    );
    // Let the seam's deferred candidate load resolve.
    await act(async () => {
      await Promise.resolve();
    });

    expect(hasA11yLabel(tree, "Search for a food")).toBe(true);
    expect(texts(tree)).toContain("Turkey breast, roasted");
    expect(texts(tree)).toContain("Turkey breast, raw");

    showKeyboard();

    // Still reachable with the keyboard up.
    expect(texts(tree)).toContain("Turkey breast, roasted");
    expect(texts(tree)).toContain("Turkey breast, raw");
  });

  it("keeps the Save action present and scrolls it clear of the keyboard (override)", async () => {
    const tree = await mount(<CorrectionSheet {...baseProps()} e2eInitialMode="override" />);
    expect(hasA11yLabel(tree, "Save Calories override")).toBe(true);

    const sv = scrollView(tree);
    const scrollToEnd = jest.fn();
    // The bottom-anchored override action is scrolled above the keyboard as it
    // rises, so Save stays visible without a manual drag.
    (sv.instance as unknown as { scrollToEnd: unknown }).scrollToEnd = scrollToEnd;

    showKeyboard();

    expect(hasA11yLabel(tree, "Save Calories override")).toBe(true);
    expect(scrollToEnd).toHaveBeenCalled();
  });

  it("scrolls the search field to the top (not the list end) when the keyboard rises", async () => {
    const listCandidates = jest.fn().mockResolvedValue([candidate()]);
    const tree = await mount(
      <CorrectionSheet {...baseProps({ listCandidates })} e2eInitialMode="change-match" />,
    );
    await act(async () => {
      await Promise.resolve();
    });

    // Report the change-match panel's offset within the scroll content (no
    // layout pass runs under react-test-renderer, so drive onLayout directly).
    const panelWrapper = tree.root.findByType(ChangeMatchPanel).parent!;
    act(() => {
      panelWrapper.props.onLayout({ nativeEvent: { layout: { y: 240 } } });
    });

    const sv = scrollView(tree);
    const scrollTo = jest.fn();
    const scrollToEnd = jest.fn();
    Object.assign(sv.instance as object, { scrollTo, scrollToEnd });

    showKeyboard();

    // The search field is brought to the top of the space above the keyboard —
    // never yanked to the list end (which would hide the field being typed in).
    expect(scrollTo).toHaveBeenCalledWith(expect.objectContaining({ y: 240 }));
    expect(scrollToEnd).not.toHaveBeenCalled();
  });
});
