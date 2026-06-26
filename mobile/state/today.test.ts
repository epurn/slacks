import {
  isOptimisticId,
  optimisticLogEvent,
  reconcileEvents,
  sortByNewest,
  statusPresentation,
} from "./today";
import type { LogEventDTO, LogEventStatus } from "@/api/logEvents";

const ALL_STATUSES: readonly LogEventStatus[] = [
  "pending",
  "processing",
  "completed",
  "failed",
  "needs_clarification",
];

function event(overrides: Partial<LogEventDTO>): LogEventDTO {
  return {
    id: "id",
    user_id: "u",
    raw_text: "two eggs",
    status: "pending",
    created_at: "2026-06-26T08:00:00Z",
    updated_at: "2026-06-26T08:00:00Z",
    ...overrides,
  };
}

describe("statusPresentation", () => {
  it("maps every contract status to a non-empty, accessible presentation", () => {
    for (const status of ALL_STATUSES) {
      const p = statusPresentation(status);
      expect(p.glyph).not.toBe("");
      expect(p.label).not.toBe("");
      expect(p.accessibilityLabel).not.toBe("");
    }
  });

  it("distinguishes pending from completed", () => {
    const pending = statusPresentation("pending");
    const completed = statusPresentation("completed");
    expect(pending.glyph).not.toBe(completed.glyph);
    expect(pending.accessibilityLabel).not.toBe(completed.accessibilityLabel);
  });

  it("uses nonjudgmental copy for a failed estimate", () => {
    const failed = statusPresentation("failed");
    expect(failed.accessibilityLabel.toLowerCase()).not.toContain("error");
    expect(failed.label).toBe("Couldn't estimate");
  });
});

describe("sortByNewest", () => {
  it("orders events by created_at descending", () => {
    const a = event({ id: "a", created_at: "2026-06-26T08:00:00Z" });
    const b = event({ id: "b", created_at: "2026-06-26T09:30:00Z" });
    const c = event({ id: "c", created_at: "2026-06-26T07:15:00Z" });
    expect(sortByNewest([a, b, c]).map((e) => e.id)).toEqual(["b", "a", "c"]);
  });

  it("does not mutate its input", () => {
    const input = [
      event({ id: "a", created_at: "2026-06-26T08:00:00Z" }),
      event({ id: "b", created_at: "2026-06-26T09:00:00Z" }),
    ];
    sortByNewest(input);
    expect(input.map((e) => e.id)).toEqual(["a", "b"]);
  });

  it("keeps insertion order for entries sharing a timestamp", () => {
    const a = event({ id: "a", created_at: "2026-06-26T08:00:00Z" });
    const b = event({ id: "b", created_at: "2026-06-26T08:00:00Z" });
    expect(sortByNewest([a, b]).map((e) => e.id)).toEqual(["a", "b"]);
  });
});

describe("reconcileEvents", () => {
  it("replaces a current event with its updated server status", () => {
    const current = [event({ id: "a", status: "pending" })];
    const fetched = [event({ id: "a", status: "completed" })];
    const result = reconcileEvents(current, fetched);
    expect(result).toHaveLength(1);
    expect(result[0]).toMatchObject({ id: "a", status: "completed" });
  });

  it("preserves an unacknowledged optimistic entry not yet on the server", () => {
    const optimistic = event({ id: "temp-0", status: "pending" });
    const stored = event({ id: "a", status: "completed" });
    const result = reconcileEvents([optimistic, stored], [stored]);
    expect(result.map((e) => e.id).sort()).toEqual(["a", "temp-0"]);
  });

  it("keeps an optimistic entry whose id the poll has not seen", () => {
    // A poll cannot tell that `server-1` is the stored form of `temp-0`, so it
    // keeps the optimistic entry; the create round-trip's id-swap (not the poll)
    // is what retires it, and polling is paused while a create is in flight.
    const current = [event({ id: "temp-0", status: "pending" })];
    const fetched = [event({ id: "server-1", status: "completed" })];
    const result = reconcileEvents(current, fetched);
    expect(result.map((e) => e.id).sort()).toEqual(["server-1", "temp-0"]);
  });

  it("does not duplicate a server event already in the timeline", () => {
    const current = [event({ id: "a", status: "pending" })];
    const fetched = [event({ id: "a", status: "processing" })];
    const result = reconcileEvents(current, fetched);
    expect(result.map((e) => e.id)).toEqual(["a"]);
  });

  it("orders the reconciled result newest-first", () => {
    const older = event({ id: "a", created_at: "2026-06-26T08:00:00Z" });
    const newer = event({ id: "b", created_at: "2026-06-26T09:00:00Z" });
    expect(reconcileEvents([], [older, newer]).map((e) => e.id)).toEqual([
      "b",
      "a",
    ]);
  });
});

describe("isOptimisticId", () => {
  it("recognizes optimistic placeholder ids and not server ids", () => {
    expect(isOptimisticId("temp-0")).toBe(true);
    expect(isOptimisticId("22222222-2222-2222-2222-222222222222")).toBe(false);
  });
});

describe("optimisticLogEvent", () => {
  it("builds a pending event from the supplied fields", () => {
    const optimistic = optimisticLogEvent({
      id: "temp-0",
      userId: "user-1",
      rawText: "cold brew",
      createdAt: "2026-06-26T10:00:00Z",
    });
    expect(optimistic).toEqual({
      id: "temp-0",
      user_id: "user-1",
      raw_text: "cold brew",
      status: "pending",
      created_at: "2026-06-26T10:00:00Z",
      updated_at: "2026-06-26T10:00:00Z",
    });
  });
});
