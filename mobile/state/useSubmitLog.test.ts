import * as React from "react";
import { act, create, type ReactTestRenderer } from "react-test-renderer";

import {
  useSubmitLog,
  type SubmitLogBridge,
  type UseSubmitLog,
} from "./useSubmitLog";
import { LogEventApiError, type LogEventDTO } from "@/api/logEvents";
import type { OutboxEntry, OutboxStore } from "@/state/outbox";
import type { ApiSession } from "@/state/session";

const SESSION: ApiSession = {
  baseUrl: "https://api.example.test",
  token: "test-token",
  userId: "22222222-2222-2222-2222-222222222222",
};

function serverEvent(overrides: Partial<LogEventDTO> = {}): LogEventDTO {
  return {
    id: "server-1",
    user_id: SESSION.userId,
    raw_text: "two eggs",
    status: "pending",
    created_at: "2026-06-28T08:00:00Z",
    updated_at: "2026-06-28T08:00:00Z",
    ...overrides,
  };
}

/** A network-layer failure (server unreachable), distinct from an API error. */
function networkError(): Error {
  return new TypeError("Network request failed");
}

/** An in-memory OutboxStore for tests, with the backing data exposed. */
function memoryStore(initial: Record<string, OutboxEntry[]> = {}): {
  store: OutboxStore;
  data: Map<string, OutboxEntry[]>;
} {
  const data = new Map<string, OutboxEntry[]>(
    Object.entries(initial).map(([k, v]) => [k, [...v]]),
  );
  const store: OutboxStore = {
    load: async (userId) => data.get(userId) ?? [],
    save: async (userId, entries) => {
      data.set(userId, [...entries]);
    },
    clear: async (userId) => {
      data.delete(userId);
    },
  };
  return { store, data };
}

/** A deterministic, monotonically-increasing idempotency-key generator. */
function sequentialKeys(): () => string {
  let n = 0;
  return () => `key-${n++}`;
}

/** A bridge of jest.fn callbacks so each lifecycle hook can be asserted. */
function spyBridge(): jest.Mocked<SubmitLogBridge> {
  return {
    insertOptimistic: jest.fn(),
    reconcileOptimistic: jest.fn(),
    rollbackOptimistic: jest.fn(),
    discardOptimistic: jest.fn(),
    acceptDrained: jest.fn(),
  };
}

const liveTrees: ReactTestRenderer[] = [];

afterEach(() => {
  act(() => {
    for (const tree of liveTrees.splice(0)) tree.unmount();
  });
  jest.restoreAllMocks();
});

/** Render the hook in a throwaway host and expose its latest return value. */
function renderSubmitLog(opts: {
  bridge: SubmitLogBridge;
  create: typeof import("@/api/logEvents").createLogEvent;
  store: OutboxStore;
  generateKey?: () => string;
  now?: () => string;
  retryIntervalMs?: number;
}) {
  let latest!: UseSubmitLog;

  function Host() {
    latest = useSubmitLog({
      session: SESSION,
      bridge: opts.bridge,
      create: opts.create,
      outboxStore: opts.store,
      generateKey: opts.generateKey ?? sequentialKeys(),
      now: opts.now ?? (() => "2026-06-28T08:00:00.000Z"),
      retryIntervalMs: opts.retryIntervalMs,
    });
    return null;
  }

  let tree!: ReactTestRenderer;
  act(() => {
    tree = create(React.createElement(Host));
  });
  liveTrees.push(tree);
  return {
    get current() {
      return latest;
    },
  };
}

describe("useSubmitLog — online success", () => {
  it("inserts optimistically, reconciles to the server event, and never enqueues", async () => {
    const bridge = spyBridge();
    const created = serverEvent({ id: "server-1", raw_text: "two eggs" });
    const create = jest.fn().mockResolvedValue(created);
    const { store, data } = memoryStore();
    const harness = renderSubmitLog({ bridge, create, store });

    act(() => harness.current.setText("  two eggs  "));
    await act(async () => {
      await harness.current.handleSubmit();
    });

    // Optimistic row inserted with the trimmed text; reconciled to the server event.
    expect(bridge.insertOptimistic).toHaveBeenCalledTimes(1);
    const optimistic = bridge.insertOptimistic.mock.calls[0][0];
    expect(optimistic.raw_text).toBe("two eggs");
    expect(bridge.reconcileOptimistic).toHaveBeenCalledWith(optimistic.id, created);

    // create called with the trimmed text + the minted idempotency key.
    expect(create).toHaveBeenCalledWith(SESSION, "two eggs", "key-0");

    // Composer cleared, no error, nothing rolled back or queued.
    expect(harness.current.text).toBe("");
    expect(harness.current.submitError).toBeNull();
    expect(bridge.rollbackOptimistic).not.toHaveBeenCalled();
    expect(bridge.discardOptimistic).not.toHaveBeenCalled();
    expect(data.get(SESSION.userId)).toBeUndefined();
  });

  it("drains an offline backlog after a successful online capture", async () => {
    jest.useFakeTimers();
    try {
      const bridge = spyBridge();
      // A backlog entry persisted from a prior offline session.
      const { store } = memoryStore({
        [SESSION.userId]: [
          {
            idempotencyKey: "backlog-1",
            userId: SESSION.userId,
            rawText: "leftover curry",
            capturedAt: "2026-06-28T07:00:00.000Z",
            syncState: "queued",
          },
        ],
      });
      const create = jest.fn().mockResolvedValue(serverEvent());
      const harness = renderSubmitLog({
        bridge,
        create,
        store,
        retryIntervalMs: 100000,
      });
      // Let the store.load() settle so the backlog is in memory.
      await act(async () => {
        await Promise.resolve();
      });

      act(() => harness.current.setText("two eggs"));
      await act(async () => {
        await harness.current.handleSubmit();
      });

      // The online success drained the backlog immediately (drainNow), without
      // waiting for the periodic retry — the backlog entry submitted too.
      const submittedTexts = create.mock.calls.map((c) => c[1]);
      expect(submittedTexts).toContain("leftover curry");
      // The drained backlog folded into the timeline via the bridge.
      expect(bridge.acceptDrained).toHaveBeenCalled();
    } finally {
      jest.useRealTimers();
    }
  });
});

describe("useSubmitLog — server error", () => {
  it("rolls back the optimistic row, restores the composer text, and surfaces the error", async () => {
    const bridge = spyBridge();
    const create = jest
      .fn()
      .mockRejectedValue(new LogEventApiError(422, "That entry couldn't be saved."));
    const { store, data } = memoryStore();
    const harness = renderSubmitLog({ bridge, create, store });

    act(() => harness.current.setText("blernsday"));
    await act(async () => {
      await harness.current.handleSubmit();
    });

    const optimisticId = bridge.insertOptimistic.mock.calls[0][0].id;
    expect(bridge.rollbackOptimistic).toHaveBeenCalledWith(optimisticId);
    // The capture is restored to the composer so retry is one tap.
    expect(harness.current.text).toBe("blernsday");
    expect(harness.current.submitError).toBe("That entry couldn't be saved.");
    // A reached-but-rejected entry is never queued offline.
    expect(bridge.discardOptimistic).not.toHaveBeenCalled();
    expect(data.get(SESSION.userId)).toBeUndefined();
  });
});

describe("useSubmitLog — unreachable", () => {
  it("discards the optimistic row and enqueues with a stable key, without restoring input", async () => {
    const bridge = spyBridge();
    const create = jest.fn().mockRejectedValue(networkError());
    const { store, data } = memoryStore();
    const harness = renderSubmitLog({ bridge, create, store });

    act(() => harness.current.setText("two eggs"));
    await act(async () => {
      await harness.current.handleSubmit();
    });

    const optimisticId = bridge.insertOptimistic.mock.calls[0][0].id;
    expect(bridge.discardOptimistic).toHaveBeenCalledWith(optimisticId);
    // No rollback-to-input: the capture is kept as an offline row, composer clear.
    expect(harness.current.text).toBe("");
    expect(harness.current.submitError).toBeNull();
    expect(bridge.rollbackOptimistic).not.toHaveBeenCalled();

    // Durably enqueued with the stable idempotency key minted at capture.
    expect(data.get(SESSION.userId)).toEqual([
      {
        idempotencyKey: "key-0",
        userId: SESSION.userId,
        rawText: "two eggs",
        capturedAt: "2026-06-28T08:00:00.000Z",
        syncState: "queued",
      },
    ]);
    expect(harness.current.reachability).toBe("offline");
    expect(harness.current.queuedCount).toBe(1);
  });

  it("reuses the same idempotency key on a reconnect drain (dedup-safe)", async () => {
    jest.useFakeTimers();
    try {
      const bridge = spyBridge();
      // Online attempt fails unreachable; the reconnect drain then succeeds.
      const create = jest
        .fn()
        .mockRejectedValueOnce(networkError())
        .mockResolvedValue(serverEvent());
      const { store } = memoryStore();
      const harness = renderSubmitLog({
        bridge,
        create,
        store,
        retryIntervalMs: 1000,
      });

      act(() => harness.current.setText("two eggs"));
      await act(async () => {
        await harness.current.handleSubmit();
      });
      expect(harness.current.queuedCount).toBe(1);

      // Advance to the reconnect probe; the drain re-submits with the SAME key.
      await act(async () => {
        jest.advanceTimersByTime(1000);
      });

      expect(create).toHaveBeenLastCalledWith(SESSION, "two eggs", "key-0");
      expect(bridge.acceptDrained).toHaveBeenCalledWith("key-0", expect.anything());
    } finally {
      jest.useRealTimers();
    }
  });
});
