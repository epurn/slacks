/**
 * E2E visual-review seam tests for Today failed / needs-clarification rows
 * (FTY-342). The presets seed the real Today data reads through the shared
 * visual-review mock-fetch override and render ClusterView's existing EntryRow
 * branches on initial load — no live backend and no scripted taps.
 */

import { act, type ReactTestRenderer } from "react-test-renderer";

import { getDailySummary } from "@/api/dailySummary";
import {
  getLogEventClarification,
  listTodayLogEventEntries,
  listTodayLogEvents,
} from "@/api/logEvents";
import { TodayScreen } from "@/components/TodayScreen";
import {
  activateVisualReviewPreset,
  getVisualReviewPreset,
  VisualReviewSettleOverlay,
} from "@/e2e/visualReview";
import { __deactivateVisualReview } from "@/e2e/visualReview/session";
import { QUIET_MS } from "@/e2e/visualReview/VisualReviewSettleOverlay";
import { createE2EMockFetch, installE2EMockFetch } from "@/e2e/launchMode";
import { E2E_SESSION } from "@/e2e/fixtures";
import { mockReduceMotion } from "@/testUtils/reduceMotion";

import {
  INACTIVE,
  cleanupTrees,
  hasA11yLabel,
  mount,
  summary,
  textContent,
} from "./todayTestUtils";
import {
  TODAY_FAILED_PRESET_NAME,
  TODAY_NEEDS_CLARIFICATION_PRESET_NAME,
  TODAY_PARTIALLY_RESOLVED_PRESET_NAME,
} from "./visualReviewEntryRows";

jest.mock("expo-router", () => ({
  usePathname: () => "/",
}));

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

jest.mock("expo-camera", () => ({
  useCameraPermissions: jest.fn(() => [
    { status: "granted", granted: true, canAskAgain: false, expires: "never" },
    jest.fn().mockResolvedValue({ status: "granted", granted: true }),
    jest.fn().mockResolvedValue({ status: "granted", granted: true }),
  ]),
  CameraView: jest.fn(() => null),
}));

jest.mock("expo-linking", () => ({
  openSettings: jest.fn().mockResolvedValue(undefined),
}));

const gThis = globalThis as Record<string, unknown>;
const ORIGINAL_DEV = gThis["__DEV__"] as boolean;
const ORIGINAL_E2E_ENV = process.env.EXPO_PUBLIC_SLACKS_E2E;

function setE2E(on: boolean): void {
  gThis["__DEV__"] = on;
  if (on) {
    process.env["EXPO_PUBLIC_SLACKS_E2E"] = "true";
  } else {
    delete process.env["EXPO_PUBLIC_SLACKS_E2E"];
  }
}

function mountTodayWithPreset(presetName: string): ReactTestRenderer {
  const mockFetch = createE2EMockFetch();
  activateVisualReviewPreset(presetName, null);
  return mount(
    <>
      <TodayScreen
        session={E2E_SESSION}
        load={(session) => listTodayLogEvents(session, undefined, mockFetch)}
        loadEntries={(session) =>
          listTodayLogEventEntries(session, undefined, mockFetch)
        }
        getDailySummary={(session) =>
          getDailySummary(session, undefined, mockFetch)
        }
        getClarification={(session, eventId) =>
          getLogEventClarification(session, eventId, mockFetch)
        }
        useActive={INACTIVE}
      />
      <VisualReviewSettleOverlay />
    </>,
  );
}

beforeEach(() => {
  mockReduceMotion(false);
});

afterEach(() => {
  cleanupTrees();
  __deactivateVisualReview();
  gThis["__DEV__"] = ORIGINAL_DEV;
  if (ORIGINAL_E2E_ENV === undefined) {
    delete process.env["EXPO_PUBLIC_SLACKS_E2E"];
  } else {
    process.env["EXPO_PUBLIC_SLACKS_E2E"] = ORIGINAL_E2E_ENV;
  }
});

describe("today failed / needs_clarification visual-review EntryRow presets", () => {
  it("registers all three presets through the FTY-247 API with the shared Today settled path", () => {
    for (const name of [
      TODAY_FAILED_PRESET_NAME,
      TODAY_NEEDS_CLARIFICATION_PRESET_NAME,
      TODAY_PARTIALLY_RESOLVED_PRESET_NAME,
    ]) {
      const preset = getVisualReviewPreset(name);
      expect(preset).toBeDefined();
      expect(preset?.route).toBe("/");
      expect(preset?.settledPath).toBe("/");
    }
  });

  it("serves contract-consistent daily summaries: failed is excluded from uncounted_entries, clarify counts one", () => {
    const summaryCtx = {
      url: "https://e2e.invalid/daily-summary",
      method: "GET",
      pathEnd: "/daily-summary",
    };
    const summaryFor = (name: string): { uncounted_entries: number } => {
      const preset = getVisualReviewPreset(name);
      const response = preset?.responses?.find((r) => r.match(summaryCtx));
      expect(response).toBeDefined();
      return response?.body as { uncounted_entries: number };
    };

    // daily-summary.md excludes `failed` events (a distinct retry state) from
    // uncounted_entries; an event-level needs_clarification contributes one, and
    // a partially_resolved event's single open component contributes one (its
    // resolved sibling counts in intake instead).
    expect(summaryFor(TODAY_FAILED_PRESET_NAME).uncounted_entries).toBe(0);
    expect(
      summaryFor(TODAY_NEEDS_CLARIFICATION_PRESET_NAME).uncounted_entries,
    ).toBe(1);
    expect(
      summaryFor(TODAY_PARTIALLY_RESOLVED_PRESET_NAME).uncounted_entries,
    ).toBe(1);
  });

  it("opens today.failed from the E2E fixture seam and exposes the shared settled marker", async () => {
    jest.useFakeTimers();
    try {
      setE2E(true);
      const tree = mountTodayWithPreset(TODAY_FAILED_PRESET_NAME);
      await act(async () => {
        await Promise.resolve();
      });

      expect(textContent(tree)).toContain("Couldn");
      expect(hasA11yLabel(tree, "Retry")).toBe(true);
      expect(hasA11yLabel(tree, "Edit as text")).toBe(true);

      const marker = `visual-review-settled:${TODAY_FAILED_PRESET_NAME}`;
      expect(hasA11yLabel(tree, marker)).toBe(false);

      await act(async () => {
        jest.advanceTimersByTime(QUIET_MS + 50);
        await Promise.resolve();
      });
      expect(hasA11yLabel(tree, marker)).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });

  it("opens today.needs_clarification from the E2E fixture seam and exposes the shared settled marker", async () => {
    jest.useFakeTimers();
    try {
      setE2E(true);
      const tree = mountTodayWithPreset(TODAY_NEEDS_CLARIFICATION_PRESET_NAME);
      await act(async () => {
        await Promise.resolve();
      });

      expect(textContent(tree)).toContain("coffee");
      expect(textContent(tree)).toContain("Add a detail");
      expect(hasA11yLabel(tree, "coffee, needs a detail, uncounted")).toBe(true);

      const marker = `visual-review-settled:${TODAY_NEEDS_CLARIFICATION_PRESET_NAME}`;
      expect(hasA11yLabel(tree, marker)).toBe(false);

      await act(async () => {
        jest.advanceTimersByTime(QUIET_MS + 50);
        await Promise.resolve();
      });
      expect(hasA11yLabel(tree, marker)).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });

  it("opens today.partially_resolved: counted sibling row + item-named pending-question row, then the settled marker", async () => {
    jest.useFakeTimers();
    try {
      setE2E(true);
      const tree = mountTodayWithPreset(TODAY_PARTIALLY_RESOLVED_PRESET_NAME);
      await act(async () => {
        await Promise.resolve();
      });

      const content = textContent(tree);
      // The committed sibling renders as a normal counted row (name · kcal)...
      expect(content).toContain("Greek yogurt");
      expect(content).toContain("140 kcal");
      // ...and the open component renders one item-named pending-question row.
      expect(content).toContain("How much hummus?");
      expect(hasA11yLabel(tree, "How much hummus?, needs a detail, uncounted")).toBe(
        true,
      );
      // The raw diary phrase is never surfaced as a row on a partial event.
      expect(content).not.toContain("greek yogurt and some hummus");

      const marker = `visual-review-settled:${TODAY_PARTIALLY_RESOLVED_PRESET_NAME}`;
      expect(hasA11yLabel(tree, marker)).toBe(false);

      await act(async () => {
        jest.advanceTimersByTime(QUIET_MS + 50);
        await Promise.resolve();
      });
      expect(hasA11yLabel(tree, marker)).toBe(true);
    } finally {
      jest.useRealTimers();
    }
  });

  it("is inert outside isE2EMode: no fixture response or settled marker appears", async () => {
    setE2E(false);
    const originalFetch = globalThis.fetch;
    activateVisualReviewPreset(TODAY_FAILED_PRESET_NAME, null);
    installE2EMockFetch();
    expect(globalThis.fetch).toBe(originalFetch);

    const tree = mount(
      <>
        <TodayScreen
          session={E2E_SESSION}
          load={jest.fn().mockResolvedValue([])}
          loadEntries={jest.fn().mockResolvedValue([])}
          getDailySummary={jest.fn().mockResolvedValue(summary())}
          useActive={INACTIVE}
        />
        <VisualReviewSettleOverlay />
      </>,
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(textContent(tree)).not.toContain("Couldn");
    expect(hasA11yLabel(tree, `visual-review-settled:${TODAY_FAILED_PRESET_NAME}`)).toBe(
      false,
    );
  });
});
