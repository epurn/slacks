import {
  createOutboxEntry,
  drainOutbox,
  generateIdempotencyKey,
  hasQueuedWork,
  mergeDrainResult,
  normalizeLoaded,
  pendingCount,
  type OutboxEntry,
} from "./outbox";
import { LogEventApiError, type LogEventDTO } from "@/api/logEvents";

const USER = "11111111-1111-1111-1111-111111111111";

function entry(overrides: Partial<OutboxEntry> = {}): OutboxEntry {
  return {
    idempotencyKey: "key-1",
    userId: USER,
    rawText: "two eggs",
    capturedAt: "2026-06-28T08:00:00Z",
    syncState: "queued",
    ...overrides,
  };
}

function dto(overrides: Partial<LogEventDTO> = {}): LogEventDTO {
  return {
    id: "server-1",
    user_id: USER,
    raw_text: "two eggs",
    name: null,
    status: "pending",
    created_at: "2026-06-28T08:00:01Z",
    updated_at: "2026-06-28T08:00:01Z",
    ...overrides,
  };
}

/** A network-layer failure: the server was never reached. */
function networkError(): Error {
  return new TypeError("Network request failed");
}

describe("generateIdempotencyKey", () => {
  it("produces distinct v4-shaped UUIDs", () => {
    const keys = new Set(
      Array.from({ length: 200 }, () => generateIdempotencyKey()),
    );
    expect(keys.size).toBe(200);
    for (const key of keys) {
      expect(key).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
      );
    }
  });
});

describe("createOutboxEntry", () => {
  it("starts a capture in the queued state with the given key", () => {
    const e = createOutboxEntry({
      idempotencyKey: "k",
      userId: USER,
      rawText: "apple",
      capturedAt: "2026-06-28T09:00:00Z",
    });
    expect(e.syncState).toBe("queued");
    expect(e.idempotencyKey).toBe("k");
    expect(e.rawText).toBe("apple");
  });
});

describe("normalizeLoaded", () => {
  it("resets an interrupted submitting entry to queued and drops accepted", () => {
    const loaded = [
      entry({ idempotencyKey: "a", syncState: "submitting" }),
      entry({ idempotencyKey: "b", syncState: "accepted" }),
      entry({ idempotencyKey: "c", syncState: "queued" }),
    ];
    const result = normalizeLoaded(loaded);
    expect(result.map((e) => e.idempotencyKey)).toEqual(["a", "c"]);
    expect(result[0].syncState).toBe("queued");
  });
});

describe("drainOutbox — reconnect sync", () => {
  it("submits each queued entry and accepts it on success", async () => {
    const submit = jest.fn().mockResolvedValue(dto());
    const result = await drainOutbox({
      entries: [entry({ idempotencyKey: "a" })],
      submit,
    });

    expect(submit).toHaveBeenCalledTimes(1);
    // The submit was driven from the entry, so it carries the same key.
    expect(submit.mock.calls[0][0]).toMatchObject({ idempotencyKey: "a" });
    expect(result.entries).toEqual([]); // accepted entries leave the queue
    expect(result.accepted).toHaveLength(1);
    expect(result.accepted[0].event.id).toBe("server-1");
    expect(result.reachedServer).toBe(true);
  });
});

describe("drainOutbox — dedup on retry (no duplicate)", () => {
  it("reuses the same idempotency key across retries and converges to one accepted item", async () => {
    const e = entry({ idempotencyKey: "stable-key" });

    // First drain: the response is lost to a network failure *after* the server
    // already accepted it (ambiguous failure). The entry stays queued.
    const lostThenReplay = jest
      .fn()
      .mockRejectedValueOnce(networkError()) // response lost
      .mockResolvedValueOnce(dto({ id: "the-one-and-only" })); // idempotent replay

    const first = await drainOutbox({ entries: [e], submit: lostThenReplay });
    expect(first.entries).toHaveLength(1);
    expect(first.entries[0].syncState).toBe("queued");
    expect(first.accepted).toHaveLength(0);

    // Second drain: retried with the SAME key → server returns the existing
    // event (200 replay). Exactly one accepted item; no duplicate.
    const second = await drainOutbox({
      entries: first.entries,
      submit: lostThenReplay,
    });

    expect(second.accepted).toHaveLength(1);
    expect(second.accepted[0].event.id).toBe("the-one-and-only");
    expect(second.entries).toEqual([]);

    // Both attempts submitted with the identical, never-regenerated key.
    expect(lostThenReplay.mock.calls[0][0].idempotencyKey).toBe("stable-key");
    expect(lostThenReplay.mock.calls[1][0].idempotencyKey).toBe("stable-key");
  });
});

describe("drainOutbox — transient-failure resilience", () => {
  it("keeps an entry queued (not dropped, not duplicated) on a network failure", async () => {
    const submit = jest.fn().mockRejectedValue(networkError());
    const result = await drainOutbox({
      entries: [entry({ idempotencyKey: "a" })],
      submit,
    });

    expect(result.entries).toHaveLength(1);
    expect(result.entries[0].syncState).toBe("queued");
    expect(result.accepted).toHaveLength(0);
    expect(result.reachedServer).toBe(false);
  });

  it("stops draining the rest once the connection drops mid-pass", async () => {
    const submit = jest
      .fn()
      .mockResolvedValueOnce(dto({ id: "s1" }))
      .mockRejectedValueOnce(networkError())
      .mockResolvedValueOnce(dto({ id: "s3" }));

    const result = await drainOutbox({
      entries: [
        entry({ idempotencyKey: "a" }),
        entry({ idempotencyKey: "b" }),
        entry({ idempotencyKey: "c" }),
      ],
      submit,
    });

    // a accepted; b failed network and stays queued; c never attempted.
    expect(submit).toHaveBeenCalledTimes(2);
    expect(result.accepted.map((a) => a.entry.idempotencyKey)).toEqual(["a"]);
    expect(result.entries.map((e) => e.idempotencyKey)).toEqual(["b", "c"]);
    expect(result.entries.every((e) => e.syncState === "queued")).toBe(true);
  });

  it.each([500, 503, 429, 401])(
    "keeps an entry queued and stops the pass on a transient %d (server reachable)",
    async (status) => {
      const submit = jest
        .fn()
        .mockRejectedValueOnce(new LogEventApiError(status, "transient"))
        .mockResolvedValueOnce(dto({ id: "s2" }));

      const result = await drainOutbox({
        entries: [
          entry({ idempotencyKey: "a" }),
          entry({ idempotencyKey: "b" }),
        ],
        submit,
      });

      // a hit a transient error and stays queued; b is never attempted this pass.
      expect(submit).toHaveBeenCalledTimes(1);
      expect(result.accepted).toHaveLength(0);
      expect(result.entries.map((e) => e.idempotencyKey)).toEqual(["a", "b"]);
      expect(result.entries.every((e) => e.syncState === "queued")).toBe(true);
      // The server answered, so we did reach it — this is online, not offline.
      expect(result.reachedServer).toBe(true);
    },
  );

  it("marks a server-rejected entry failed (non-transient) and keeps draining", async () => {
    const submit = jest
      .fn()
      .mockRejectedValueOnce(new LogEventApiError(422, "bad"))
      .mockResolvedValueOnce(dto({ id: "s2" }));

    const result = await drainOutbox({
      entries: [
        entry({ idempotencyKey: "a" }),
        entry({ idempotencyKey: "b" }),
      ],
      submit,
    });

    expect(submit).toHaveBeenCalledTimes(2);
    const failed = result.entries.find((e) => e.idempotencyKey === "a");
    expect(failed?.syncState).toBe("failed");
    expect(result.accepted.map((a) => a.entry.idempotencyKey)).toEqual(["b"]);
    expect(result.reachedServer).toBe(true);
  });
});

describe("queue counters", () => {
  it("pendingCount counts queued + submitting, not failed/accepted", () => {
    const entries = [
      entry({ idempotencyKey: "a", syncState: "queued" }),
      entry({ idempotencyKey: "b", syncState: "submitting" }),
      entry({ idempotencyKey: "c", syncState: "failed" }),
    ];
    expect(pendingCount(entries)).toBe(2);
  });

  it("hasQueuedWork is true only while a queued entry remains", () => {
    expect(hasQueuedWork([entry({ syncState: "queued" })])).toBe(true);
    expect(hasQueuedWork([entry({ syncState: "failed" })])).toBe(false);
    expect(hasQueuedWork([])).toBe(false);
  });
});

describe("mergeDrainResult", () => {
  it("preserves an entry captured during the drain (key outside the snapshot)", () => {
    const snapshotKeys = new Set(["a"]);
    // The drain accepted `a` (so it's gone), but `b` was enqueued meanwhile.
    const latest = [
      entry({ idempotencyKey: "a", syncState: "submitting" }),
      entry({ idempotencyKey: "b", syncState: "queued" }),
    ];
    const drained: readonly OutboxEntry[] = [];
    expect(
      mergeDrainResult(latest, snapshotKeys, drained).map(
        (e) => e.idempotencyKey,
      ),
    ).toEqual(["b"]);
  });

  it("keeps the drain's resolved view of the snapshot and appends new entries", () => {
    const snapshotKeys = new Set(["a"]);
    const latest = [
      entry({ idempotencyKey: "a", syncState: "submitting" }),
      entry({ idempotencyKey: "b", syncState: "queued" }),
    ];
    // The drain marked `a` failed (kept for visibility).
    const drained = [entry({ idempotencyKey: "a", syncState: "failed" })];
    const merged = mergeDrainResult(latest, snapshotKeys, drained);
    expect(merged.map((e) => [e.idempotencyKey, e.syncState])).toEqual([
      ["a", "failed"],
      ["b", "queued"],
    ]);
  });

  it("is a no-op shape when nothing was captured during the drain", () => {
    const snapshotKeys = new Set(["a"]);
    const drained = [entry({ idempotencyKey: "a", syncState: "queued" })];
    expect(mergeDrainResult(drained, snapshotKeys, drained)).toEqual(drained);
  });
});
