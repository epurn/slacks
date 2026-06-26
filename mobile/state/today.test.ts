import {
  optimisticLogEvent,
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
