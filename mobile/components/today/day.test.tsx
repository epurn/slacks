import { act, type ReactTestRenderer } from "react-test-renderer";

import DayScreen from "../../app/day";
import type { ItemSourceDTO } from "@/api/derivedItems";
import type { LogEventEntryDTO } from "@/api/logEvents";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

import {
  SESSION,
  cleanupTrees,
  event,
  foodItem,
  mount,
  summary,
  textContent,
} from "./todayTestUtils";

// expo-symbols is a native module — stub SymbolView so the provenance / status
// SF Symbols render and expose their name + a11y label (same pattern as the
// Today suites).
jest.mock("expo-symbols", () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactNative = require("react-native");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const ReactLib = require("react");
  return {
    SymbolView: ({
      name,
      accessibilityLabel,
    }: {
      name: string;
      accessibilityLabel?: string;
    }) =>
      ReactLib.createElement(ReactNative.View, {
        testID: `sf-symbol-${String(name)}`,
        accessibilityLabel,
      }),
  };
});

// The past-day route reads its date from expo-router and pops back on the header
// button; stub both so the screen renders without a live navigation tree. The
// `mock`-prefix lets the jest.mock factory reference these (jest allowlist rule).
let mockSearchParams: { date?: string } = { date: "2026-06-28" };
const mockBack = jest.fn();
jest.mock("expo-router", () => ({
  useLocalSearchParams: () => mockSearchParams,
  useRouter: () => ({ back: mockBack, push: jest.fn() }),
}));

function usdaSource(): ItemSourceDTO {
  return {
    source_type: "trusted_nutrition_database",
    label: "USDA",
    ref: "usda_fdc:168880",
    estimate_basis: null,
  };
}

/** One completed entry (event + its resolved item rows), by-date-feed shaped. */
function completedEntry(): LogEventEntryDTO {
  return {
    event: event({
      id: "evt-1",
      status: "completed",
      raw_text: "greek yogurt",
      created_at: "2026-06-28T08:00:00Z",
      updated_at: "2026-06-28T08:00:00Z",
    }),
    items: [
      foodItem({
        id: "item-1",
        log_event_id: "evt-1",
        name: "Greek yogurt",
        calories: 150,
        source: usdaSource(),
        is_edited: false,
      }),
    ],
  };
}

/** An unresolved needs_clarification entry from the past day (no item rows). */
function needsClarificationEntry(): LogEventEntryDTO {
  return {
    event: event({
      id: "evt-nc",
      status: "needs_clarification",
      raw_text: "some cereal",
      created_at: "2026-06-28T08:00:00Z",
      updated_at: "2026-06-28T08:00:00Z",
    }),
    items: [],
  };
}

/** An unresolved failed-parse entry from the past day (no item rows). */
function failedEntry(): LogEventEntryDTO {
  return {
    event: event({
      id: "evt-failed",
      status: "failed",
      raw_text: "asdkfj",
      created_at: "2026-06-28T09:00:00Z",
      updated_at: "2026-06-28T09:00:00Z",
    }),
    items: [],
  };
}

function allA11yLabels(tree: ReactTestRenderer): string[] {
  return tree.root
    .findAll((n) => typeof n.props.accessibilityLabel === "string")
    .map((n) => n.props.accessibilityLabel as string);
}

function headerLabel(tree: ReactTestRenderer): string {
  return tree.root.find((n) => n.props.accessibilityRole === "header").props
    .accessibilityLabel as string;
}

beforeEach(() => {
  mockSearchParams = { date: "2026-06-28" };
  mockBack.mockReset();
  // Resolve the Reduce Motion check synchronously so the row's resolve-fade hook
  // never leaks an async setState past `act` (no animation is expected here).
  mockReduceMotion(false);
});

afterEach(() => {
  cleanupTrees();
  jest.restoreAllMocks();
});

describe("DayScreen — reuses the Today timeline (FTY-199)", () => {
  it("mounts the shared timeline fed by the entries-by-date read; rows show name · kcal · source icon", async () => {
    const loadEntries = jest.fn().mockResolvedValue([completedEntry()]);
    const getDailySummary = jest.fn().mockResolvedValue(summary());

    const tree = mount(
      <DayScreen
        session={SESSION}
        loadEntries={loadEntries}
        getDailySummary={getDailySummary}
      />,
    );
    await act(async () => {});

    // Fed by FTY-198's read for the selected date.
    expect(loadEntries).toHaveBeenCalledWith(expect.anything(), "2026-06-28");

    // The shared Today timeline (not a bespoke list) rendered its entries body.
    expect(
      tree.root.findAll((n) => n.props.testID === "today-timeline-with-entries").length,
    ).toBeGreaterThanOrEqual(1);

    // Row: name · kcal.
    const text = textContent(tree);
    expect(text).toContain("Greek yogurt");
    expect(text).toContain("150 kcal");

    // Always-on source icon: its provenance a11y label is present.
    expect(allA11yLabels(tree).some((l) => l.includes("USDA"))).toBe(true);
  });

  it("renders the item rows read-only — no 'tap to view details' affordance", async () => {
    const tree = mount(
      <DayScreen
        session={SESSION}
        loadEntries={jest.fn().mockResolvedValue([completedEntry()])}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
      />,
    );
    await act(async () => {});

    // No interactive correction affordance on a historical day.
    expect(
      tree.root.findAll((n) => n.props.accessibilityHint === "Tap to view details"),
    ).toHaveLength(0);
    // The value + its provenance are still conveyed to VoiceOver in one label.
    expect(
      allA11yLabels(tree).some(
        (l) => l.includes("Greek yogurt") && l.includes("150 kcal") && l.includes("USDA"),
      ),
    ).toBe(true);
  });
});

describe("DayScreen — read-only, no inert CTAs (FTY-199)", () => {
  it("neutralizes the 'Add a detail' chip for a historical needs_clarification entry", async () => {
    const tree = mount(
      <DayScreen
        session={SESSION}
        loadEntries={jest.fn().mockResolvedValue([needsClarificationEntry()])}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
      />,
    );
    await act(async () => {});

    // The row still renders (calm, legible)…
    expect(
      tree.root.findAll((n) => n.props.testID === "add-a-detail-row").length,
    ).toBeGreaterThanOrEqual(1);
    // …but the inert accent CTA chip is gone, and nothing is tappable.
    expect(textContent(tree)).not.toContain("Add a detail");
    expect(
      tree.root.findAll(
        (n) => n.props.testID === "add-a-detail-row" && typeof n.props.onPress === "function",
      ),
    ).toHaveLength(0);
    // The needs-a-detail state is still conveyed to VoiceOver.
    expect(
      allA11yLabels(tree).some((l) => l.includes("needs a detail")),
    ).toBe(true);
  });

  it("neutralizes Retry / Edit-as-text for a historical failed entry", async () => {
    const tree = mount(
      <DayScreen
        session={SESSION}
        loadEntries={jest.fn().mockResolvedValue([failedEntry()])}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
      />,
    );
    await act(async () => {});

    // The failed row still renders calmly…
    expect(
      tree.root.findAll((n) => n.props.testID === "failed-parse-row").length,
    ).toBeGreaterThanOrEqual(1);
    expect(textContent(tree)).toContain("Couldn't read that");
    // …with no inert Retry / Edit-as-text buttons.
    expect(tree.root.findAll((n) => n.props.testID === "failed-retry")).toHaveLength(0);
    expect(
      tree.root.findAll((n) => n.props.testID === "failed-edit-as-text"),
    ).toHaveLength(0);
  });
});

describe("DayScreen — prose date title (FTY-199)", () => {
  it("renders a human date, never a raw ISO string, in the title and its a11y label", async () => {
    const tree = mount(
      <DayScreen
        session={SESSION}
        loadEntries={jest.fn().mockResolvedValue([completedEntry()])}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
      />,
    );
    await act(async () => {});

    const title = headerLabel(tree);
    // No YYYY-MM-DD anywhere in the header, and the title is a prose date.
    expect(title).not.toMatch(/\d{4}-\d{2}-\d{2}/);
    // "2026-06-28" is Today/Yesterday only when the suite runs on/after it;
    // otherwise it reads as "June 28". All three are prose, none are ISO.
    expect(title).toMatch(/^(Today|Yesterday|June 28)$/);

    // And no raw ISO leaks into the visible screen text either.
    expect(textContent(tree)).not.toMatch(/2026-06-28/);
  });
});

describe("DayScreen — calm states (FTY-199)", () => {
  it("shows a calm loading state while the day is in flight", () => {
    // A promise that never settles keeps the screen in its loading phase.
    const tree = mount(
      <DayScreen
        session={SESSION}
        loadEntries={jest.fn(() => new Promise(() => {}))}
        getDailySummary={jest.fn(() => new Promise(() => {}))}
      />,
    );

    expect(
      tree.root.findAll((n) => n.props.accessibilityLabel === "Loading your day").length,
    ).toBeGreaterThanOrEqual(1);
  });

  it("shows a calm empty state for a day with nothing logged", async () => {
    const tree = mount(
      <DayScreen
        session={SESSION}
        loadEntries={jest.fn().mockResolvedValue([])}
        getDailySummary={jest.fn().mockResolvedValue(
          summary({ intake: { calories: 0, protein_g: 0, carbs_g: 0, fat_g: 0 }, has_intake: false }),
        )}
      />,
    );
    await act(async () => {});

    expect(textContent(tree)).toContain("Nothing logged that day");
    // Not the Today "Log your first thing" invite — a past day is view-only.
    expect(textContent(tree)).not.toContain("Log your first thing");
  });

  it("shows a calm, retryable error state when the day fails to load", async () => {
    const tree = mount(
      <DayScreen
        session={SESSION}
        loadEntries={jest.fn().mockRejectedValue(new TypeError("Network request failed"))}
        getDailySummary={jest.fn().mockResolvedValue(summary())}
      />,
    );
    await act(async () => {});

    const text = textContent(tree);
    expect(text).toContain("Try again");
    expect(text.toLowerCase()).toContain("couldn't load");
  });
});
