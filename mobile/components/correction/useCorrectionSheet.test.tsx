/**
 * FTY-366: change-match → pick-candidate → re-resolve, end-to-end through the
 * REAL corrections client.
 *
 * Unlike `CorrectionSheet.test.tsx` (which injects mocked API functions), these
 * tests mount the sheet with its default clients and mock only `fetch`, so the
 * whole user flow runs for real: the request bodies the client constructs, the
 * backend's documented response shapes (captured from a live local backend in
 * the FTY-366 reproduction), the per-flow 422 copy mapping, and the sheet
 * adopting the result in place. Fixtures mirror the reproduced dogfood failure:
 * a model-prior count-quantity item whose chosen candidate cannot be costed.
 */

import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { ThemeProvider } from "@/theme";

import { CorrectionSheet } from "../CorrectionSheet";
import type { DerivedFoodItemDTO } from "@/api/derivedItems";
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

// expo-symbols is a native module — replace SymbolView with a View stub that
// exposes the symbol name via testID (same pattern as CorrectionSheet.test.tsx).
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
      tintColor?: string;
      size?: number;
      accessibilityLabel?: string;
    }) =>
      React.createElement(View, {
        testID: `sf-symbol-${String(name)}`,
        accessibilityLabel,
      }),
  };
});

// ─── Fixtures (shaped like the FTY-366 reproduction) ──────────────────────────

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "user-1",
};

/** A model-prior, count-quantity item — the reproduced dogfood shape. */
function roughItem(): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: "food-1",
    user_id: "user-1",
    log_event_id: "event-1",
    name: "Tuna sandwich",
    quantity_text: "1 sandwich",
    unit: "sandwich",
    amount: 1,
    status: "resolved",
    grams: 250,
    calories: 480,
    protein_g: 22,
    carbs_g: 42,
    fat_g: 24,
    calories_estimated: 480,
    protein_g_estimated: 22,
    carbs_g_estimated: 42,
    fat_g_estimated: 24,
    source: { source_type: "model_prior", label: "Rough estimate", ref: "model_prior" },
    is_edited: false,
    created_at: "2026-07-14T08:00:00Z",
    updated_at: "2026-07-14T08:00:00Z",
  };
}

const CANDIDATES_BODY = {
  candidates: [
    {
      source_type: "trusted_nutrition_database",
      source_ref: "usda_fdc:2345170",
      name: "Sandwich, tuna salad",
      basis: "per_100g",
      calories: 192,
      protein_g: 10,
      carbs_g: 17,
      fat_g: 9,
    },
    {
      source_type: "trusted_nutrition_database",
      source_ref: "usda_fdc:9999001",
      name: "Tuna salad sandwich",
      basis: "per_100g",
      calories: 210,
      protein_g: 11,
      carbs_g: 20,
      fat_g: 8,
    },
  ],
};

/** The updated DTO a successful re-resolve returns (new provenance, in place). */
function reResolvedItem(): DerivedFoodItemDTO {
  return {
    ...roughItem(),
    grams: 150,
    calories: 315,
    protein_g: 16.5,
    carbs_g: 30,
    fat_g: 12,
    calories_estimated: 315,
    protein_g_estimated: 16.5,
    carbs_g_estimated: 30,
    fat_g_estimated: 12,
    source: {
      source_type: "trusted_nutrition_database",
      label: "USDA",
      ref: "usda_fdc:9999001",
    },
  };
}

// Documented backend 422 bodies, captured verbatim from the live reproduction.
const NEEDS_CLARIFICATION_422 = {
  detail: {
    error: "needs_clarification",
    question: "How much did you have (for example, in grams, millilitres, or servings)?",
  },
};
const SOURCE_NOT_RESOLVABLE_422 = { detail: { error: "source_not_resolvable" } };

// ─── fetch mock ────────────────────────────────────────────────────────────────

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as unknown as Response;
}

/** Serve list-candidates, then each queued re-resolve response in order. */
function installFetch(reResolveQueue: Response[]): jest.Mock {
  const fetchMock = jest.fn(async (url: string) => {
    if (url.endsWith("/source-candidates")) {
      return jsonResponse(200, CANDIDATES_BODY);
    }
    if (url.endsWith("/re-resolve")) {
      const next = reResolveQueue.shift();
      if (next === undefined) throw new Error("unexpected re-resolve request");
      return next;
    }
    throw new Error("unexpected request in test");
  });
  (globalThis as { fetch: typeof fetch }).fetch =
    fetchMock as unknown as typeof fetch;
  return fetchMock;
}

const realFetch = globalThis.fetch;

// ─── Test helpers ──────────────────────────────────────────────────────────────

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

function hasA11yLabel(tree: ReactTestRenderer, label: string): boolean {
  return tree.root.findAll((n) => n.props.accessibilityLabel === label).length > 0;
}

async function pressAsync(tree: ReactTestRenderer, label: string): Promise<void> {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onPress === "function",
  );
  await act(async () => {
    node.props.onPress();
  });
}

function sheetProps() {
  return {
    item: roughItem(),
    visible: true,
    onClose: jest.fn(),
    session: SESSION,
    onItemChange: jest.fn(),
  };
}

beforeEach(() => {
  mockReduceMotion(false);
  mockCorrectionSavedHaptic.mockClear();
});

afterEach(() => {
  (globalThis as { fetch: typeof fetch }).fetch = realFetch;
  cleanupReactTestRenderers();
  jest.restoreAllMocks();
});

// ─── Flows ─────────────────────────────────────────────────────────────────────

describe("change-match re-resolve, end-to-end through the real client", () => {
  it("a successful re-resolve adopts the item in place with new provenance", async () => {
    const fetchMock = installFetch([jsonResponse(200, reResolvedItem())]);
    const props = sheetProps();
    const tree = mount(<CorrectionSheet {...props} />);

    await pressAsync(tree, "Change match");
    await pressAsync(tree, "Select Tuna salad sandwich, 210 kcal per 100g");

    // The real client sent the contract body to the re-resolve route.
    const reResolveCall = fetchMock.mock.calls.find(([url]) =>
      (url as string).endsWith("/re-resolve"),
    ) as [string, RequestInit];
    expect(JSON.parse(reResolveCall[1].body as string)).toEqual({
      source_ref: "usda_fdc:9999001",
    });

    // In place: back to the normal sheet with the new provenance visible —
    // no navigation, no dismissal.
    expect(hasA11yLabel(tree, "Change match")).toBe(true);
    expect(allText(tree)).toContain("USDA");
    expect(props.onClose).not.toHaveBeenCalled();
    expect(props.onItemChange).toHaveBeenCalledWith(
      expect.objectContaining({
        source: expect.objectContaining({ ref: "usda_fdc:9999001" }),
      }),
    );
    expect(mockCorrectionSavedHaptic).toHaveBeenCalledTimes(1);
  });

  it("a needs_clarification 422 shows the how-much follow-up, not check-the-value", async () => {
    installFetch([jsonResponse(422, NEEDS_CLARIFICATION_422)]);
    const props = sheetProps();
    const tree = mount(<CorrectionSheet {...props} />);

    await pressAsync(tree, "Change match");
    await pressAsync(tree, "Select Sandwich, tuna salad, 192 kcal per 100g");

    const text = allText(tree);
    expect(text).toContain(
      "That match needs to know how much you had. Update the amount, then try the match again.",
    );
    expect(text.toLowerCase()).not.toContain("check the value");
    // Still in the change-match panel (no silent dismissal), nothing committed.
    expect(hasA11yLabel(tree, "Cancel change match")).toBe(true);
    expect(props.onItemChange).not.toHaveBeenCalled();
    expect(mockCorrectionSavedHaptic).not.toHaveBeenCalled();
  });

  it("a source_not_resolvable 422 invites picking another match, which stays actionable", async () => {
    const fetchMock = installFetch([
      jsonResponse(422, SOURCE_NOT_RESOLVABLE_422),
      jsonResponse(200, reResolvedItem()),
    ]);
    const tree = mount(<CorrectionSheet {...sheetProps()} />);

    await pressAsync(tree, "Change match");
    await pressAsync(tree, "Select Sandwich, tuna salad, 192 kcal per 100g");

    expect(allText(tree)).toContain(
      "That match couldn't be applied. Pick a different match or search again.",
    );

    // The pick-another affordance is real, not inert: choosing the other
    // candidate issues a fresh re-resolve and completes the flow.
    await pressAsync(tree, "Select Tuna salad sandwich, 210 kcal per 100g");
    const reResolveCalls = fetchMock.mock.calls.filter(([url]) =>
      (url as string).endsWith("/re-resolve"),
    );
    expect(reResolveCalls).toHaveLength(2);
    expect(allText(tree)).toContain("USDA");
  });

  it("a request-validation 422 falls back to the plain residual message", async () => {
    installFetch([
      jsonResponse(422, {
        detail: [
          {
            type: "string_too_short",
            loc: ["body", "source_ref"],
            msg: "String should have at least 1 character",
          },
        ],
      }),
    ]);
    const tree = mount(<CorrectionSheet {...sheetProps()} />);

    await pressAsync(tree, "Change match");
    await pressAsync(tree, "Select Sandwich, tuna salad, 192 kcal per 100g");

    const text = allText(tree);
    expect(text).toContain("That match couldn't be applied. Try again.");
    expect(text.toLowerCase()).not.toContain("check the value");
  });
});
