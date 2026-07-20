import {
  clusterByTime,
  formatWallClockTime,
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
    name: null,
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
      name: null,
      status: "pending",
      created_at: "2026-06-26T10:00:00Z",
      updated_at: "2026-06-26T10:00:00Z",
    });
  });
});

describe("clusterByTime", () => {
  const WINDOW_MS = 10 * 60 * 1000; // 10 minutes

  it("returns empty when no events", () => {
    expect(clusterByTime([])).toEqual([]);
  });

  it("groups events within the grace window into one cluster, newest first", () => {
    const a = event({ id: "a", created_at: "2026-06-27T08:00:00Z" });
    const b = event({ id: "b", created_at: "2026-06-27T08:05:00Z" });
    const c = event({ id: "c", created_at: "2026-06-27T08:09:00Z" });
    const clusters = clusterByTime([a, b, c], WINDOW_MS);
    expect(clusters).toHaveLength(1);
    // Events within a cluster are newest-first (same as the overall sort)
    expect(clusters[0].events.map((e) => e.id)).toEqual(["c", "b", "a"]);
  });

  it("splits events outside the window into separate clusters", () => {
    const a = event({ id: "a", created_at: "2026-06-27T08:00:00Z" });
    const b = event({ id: "b", created_at: "2026-06-27T07:45:00Z" }); // 15 min earlier
    const clusters = clusterByTime([a, b], WINDOW_MS);
    expect(clusters).toHaveLength(2);
    expect(clusters[0].events[0].id).toBe("a"); // newest cluster first
    expect(clusters[1].events[0].id).toBe("b");
  });

  it("clusters are ordered newest first (anchor is newest event)", () => {
    const a = event({ id: "a", created_at: "2026-06-27T08:00:00Z" });
    const b = event({ id: "b", created_at: "2026-06-27T07:00:00Z" });
    const clusters = clusterByTime([a, b], WINDOW_MS);
    expect(clusters[0].anchorTime).toBe("2026-06-27T08:00:00Z");
    expect(clusters[1].anchorTime).toBe("2026-06-27T07:00:00Z");
  });

  it("a single event forms its own cluster", () => {
    const a = event({ id: "a", created_at: "2026-06-27T08:00:00Z" });
    const clusters = clusterByTime([a], WINDOW_MS);
    expect(clusters).toHaveLength(1);
    expect(clusters[0].events).toHaveLength(1);
  });

  it("exactly-at-window-boundary event joins the cluster", () => {
    const a = event({ id: "a", created_at: "2026-06-27T08:10:00Z" });
    const b = event({ id: "b", created_at: "2026-06-27T08:00:00Z" }); // exactly 10 min earlier
    const clusters = clusterByTime([a, b], WINDOW_MS);
    expect(clusters).toHaveLength(1);
  });

  it("event 1ms past the window starts a new cluster", () => {
    const a = event({ id: "a", created_at: "2026-06-27T08:10:00.001Z" });
    const b = event({ id: "b", created_at: "2026-06-27T08:00:00Z" }); // 10min+1ms earlier
    const clusters = clusterByTime([a, b], WINDOW_MS);
    expect(clusters).toHaveLength(2);
  });
});

describe("formatWallClockTime", () => {
  // Format every instant in a fixed zone (UTC) so the assertions are stable
  // regardless of the machine running the tests; timezone conversion itself is
  // covered by its own case below.
  const UTC = "UTC";

  it("regression: 11:14 AM renders AM, never PM (audit A6)", () => {
    // The exact bug this story fixes: a morning instant must not flip to PM.
    expect(formatWallClockTime("2026-06-27T11:14:00Z", UTC)).toBe("11:14 AM");
  });

  it("formats a mid-afternoon instant as PM", () => {
    expect(formatWallClockTime("2026-06-27T15:30:00Z", UTC)).toBe("3:30 PM");
  });

  describe("12-hour boundary cases", () => {
    it("midnight is 12:xx AM, not 00:xx or 12:xx PM", () => {
      expect(formatWallClockTime("2026-06-27T00:14:00Z", UTC)).toBe("12:14 AM");
    });

    it("exactly midnight is 12:00 AM", () => {
      expect(formatWallClockTime("2026-06-27T00:00:00Z", UTC)).toBe("12:00 AM");
    });

    it("noon is 12:xx PM, not 00:xx or 12:xx AM", () => {
      expect(formatWallClockTime("2026-06-27T12:14:00Z", UTC)).toBe("12:14 PM");
    });

    it("exactly noon is 12:00 PM", () => {
      expect(formatWallClockTime("2026-06-27T12:00:00Z", UTC)).toBe("12:00 PM");
    });

    it("one minute before noon is still AM", () => {
      expect(formatWallClockTime("2026-06-27T11:59:00Z", UTC)).toBe("11:59 AM");
    });

    it("one minute after noon flips to PM", () => {
      expect(formatWallClockTime("2026-06-27T12:01:00Z", UTC)).toBe("12:01 PM");
    });

    it("one minute before midnight is 11:59 PM", () => {
      expect(formatWallClockTime("2026-06-27T23:59:00Z", UTC)).toBe("11:59 PM");
    });

    it("one minute after midnight is 12:01 AM", () => {
      expect(formatWallClockTime("2026-06-27T00:01:00Z", UTC)).toBe("12:01 AM");
    });
  });

  it("converts the instant into the requested timezone's wall clock", () => {
    // 11:14 UTC is 06:14 in New York (EDT, UTC-4) on this date — the label must
    // reflect the local wall clock, not UTC.
    expect(formatWallClockTime("2026-06-27T11:14:00Z", "America/New_York")).toBe(
      "7:14 AM",
    );
  });

  it("crosses the local day boundary when the zone shifts the date", () => {
    // 02:30 UTC is the previous evening (22:30, 10:30 PM) in New York.
    expect(formatWallClockTime("2026-06-27T02:30:00Z", "America/New_York")).toBe(
      "10:30 PM",
    );
  });

  it("pads minutes to two digits", () => {
    expect(formatWallClockTime("2026-06-27T09:05:00Z", UTC)).toBe("9:05 AM");
  });

  it("returns empty string for an unparseable timestamp", () => {
    expect(formatWallClockTime("not-a-date", UTC)).toBe("");
  });

  it("returns empty string for an invalid timezone rather than throwing", () => {
    expect(formatWallClockTime("2026-06-27T11:14:00Z", "Not/AZone")).toBe("");
  });
});
