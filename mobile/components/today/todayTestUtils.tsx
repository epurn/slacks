import { act, create as render, type ReactTestRenderer } from "react-test-renderer";
import { SafeAreaProvider } from "react-native-safe-area-context";

import type { DailySummaryDTO } from "@/api/dailySummary";
import type { DerivedFoodItemDTO } from "@/api/derivedItems";
import type { LogEventDTO } from "@/api/logEvents";
import type { SavedFoodDTO } from "@/api/savedFoods";
import type { OutboxEntry, OutboxStore } from "@/state/outbox";
import type { Session } from "@/state/session";

/**
 * Shared scaffolding for the split Today test suites (FTY-205). Holds the
 * session/event/item/summary factories, the SafeAreaProvider-wrapped `mount`
 * with per-suite tree cleanup, and the tree-walking query helpers. The
 * per-file `jest.mock(...)` declarations stay in each suite (jest hoists them
 * per file); only these pure helpers are shared.
 */

export const SESSION: Session = {
  serverUrl: "https://api.example.test",
  token: "test-token",
  userId: "22222222-2222-2222-2222-222222222222",
};

// Polling is driven by an injected screen-active signal; default it off so the
// non-polling tests stay deterministic and never touch a navigation container.
export const INACTIVE = () => false;

export function event(overrides: Partial<LogEventDTO>): LogEventDTO {
  return {
    id: "id",
    user_id: SESSION!.userId,
    raw_text: "two eggs and toast",
    status: "pending",
    created_at: "2026-06-26T08:00:00Z",
    updated_at: "2026-06-26T08:00:00Z",
    ...overrides,
  };
}

export function foodItem(
  overrides: Partial<DerivedFoodItemDTO> = {},
): DerivedFoodItemDTO {
  return {
    item_type: "food",
    id: "item-1",
    user_id: SESSION!.userId,
    log_event_id: "a",
    name: "Greek yogurt",
    quantity_text: "1 cup",
    unit: "cup",
    amount: 1,
    status: "resolved",
    grams: 245,
    calories: 150,
    protein_g: 20,
    carbs_g: 8,
    fat_g: 4,
    calories_estimated: 150,
    protein_g_estimated: 20,
    carbs_g_estimated: 8,
    fat_g_estimated: 4,
    created_at: "2026-06-26T08:00:00Z",
    updated_at: "2026-06-26T08:00:00Z",
    ...overrides,
  };
}

export function savedFood(overrides: Partial<SavedFoodDTO> = {}): SavedFoodDTO {
  return {
    id: "sf-1",
    user_id: SESSION!.userId,
    name: "Greek yogurt",
    calories: 200,
    protein_g: 22,
    carbs_g: 10,
    fat_g: 5,
    serving_size: 1,
    serving_unit: "cup",
    source: "saved_from_correction",
    created_at: "2026-06-27T10:00:00Z",
    updated_at: "2026-06-27T10:00:00Z",
    ...overrides,
  };
}

export function summary(overrides: Partial<DailySummaryDTO> = {}): DailySummaryDTO {
  return {
    date: "2026-06-27",
    intake: { calories: 1234, protein_g: 70, carbs_g: 120, fat_g: 40 },
    has_intake: true,
    uncounted_entries: 0,
    target: {
      calories: { effective: 2000, derived: 2000, source: "derived" },
      protein_g: { effective: 128, derived: 128, source: "derived" },
      carbs_g: { effective: 148, derived: 148, source: "derived" },
      fat_g: { effective: 64, derived: 64, source: "derived" },
    },
    exercise: { active_calories: 0 },
    ...overrides,
  };
}

// Unmount every tree after each test so a background interval (e.g. the offline
// outbox retry timer) can never fire into a later test and update an unmounted
// component. Each suite registers `afterEach(cleanupTrees)`.
const activeTrees: ReactTestRenderer[] = [];

export function cleanupTrees(): void {
  for (const tree of activeTrees) {
    try {
      act(() => tree.unmount());
    } catch {
      // Already unmounted / torn down — ignore.
    }
  }
  activeTrees.length = 0;
}

// SafeAreaProvider needs frame/insets metrics in a non-native test environment.
export function mount(element: React.ReactElement): ReactTestRenderer {
  let tree!: ReactTestRenderer;
  act(() => {
    tree = render(
      <SafeAreaProvider
        initialMetrics={{
          frame: { x: 0, y: 0, width: 390, height: 844 },
          insets: { top: 47, left: 0, right: 0, bottom: 34 },
        }}
      >
        {element}
      </SafeAreaProvider>,
    );
  });
  activeTrees.push(tree);
  return tree;
}

export function textContent(tree: ReactTestRenderer): string {
  return tree.root
    .findAll((n) => typeof n.props.children === "string")
    .map((n) => n.props.children as string)
    .join(" ");
}

export function hasA11yLabel(tree: ReactTestRenderer, label: string): boolean {
  return tree.root.findAll((n) => n.props.accessibilityLabel === label).length > 0;
}

/**
 * Count pending/processing skeleton rows (FTY-180) by their host container —
 * `accessibilityRole="progressbar"` plus the status label. Matching on both
 * props (not just the label) avoids double-counting the `ItemTimelineRow`
 * composite fiber, whose own props also carry `accessibilityLabel` alongside
 * the host `View` it renders.
 */
export function countPendingRows(tree: ReactTestRenderer, label: string): number {
  return tree.root.findAll(
    (n) =>
      n.props.accessibilityRole === "progressbar" &&
      n.props.accessibilityLabel === label,
  ).length;
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

export function inputValue(tree: ReactTestRenderer, label: string): string {
  const node = tree.root.find(
    (n) =>
      n.props.accessibilityLabel === label &&
      typeof n.props.onChangeText === "function",
  );
  return node.props.value as string;
}

/** A network-layer failure (server unreachable), distinct from an API error. */
export function networkError(): Error {
  return new TypeError("Network request failed");
}

/** An in-memory OutboxStore for tests, with the backing data exposed. */
export function memoryStore(initial: Record<string, OutboxEntry[]> = {}): {
  store: OutboxStore;
  data: Map<string, OutboxEntry[]>;
} {
  const data = new Map<string, OutboxEntry[]>(
    Object.entries(initial).map(([k, v]) => [k, [...v]]),
  );
  // Keyed by `owner.userId` (these Today tests use a single server); the FTY-277
  // owner is server+user, and cross-server scoping is covered in outboxStore.test.
  const store: OutboxStore = {
    load: async (owner) => data.get(owner.userId) ?? [],
    save: async (owner, entries) => {
      data.set(owner.userId, [...entries]);
    },
    clear: async (owner) => {
      data.delete(owner.userId);
    },
  };
  return { store, data };
}

/** A deterministic, monotonically-increasing idempotency-key generator. */
export function sequentialKeys(): () => string {
  let n = 0;
  return () => `key-${n++}`;
}

/**
 * A clarification read that returns no persisted question — the clarify sheet
 * falls back to the generic prompt + free-text. Injected so clarify-mode tests
 * that don't exercise the question stay deterministic (no real fetch).
 */
export function emptyClarification(): jest.Mock {
  return jest.fn().mockResolvedValue({ questions: [] });
}
