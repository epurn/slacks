import {
  MOCK_TODAY_ENTRIES,
  selectComplete,
  selectPending,
  statusAccessibilityLabel,
  summarizeDay,
  type TodayEntry,
} from "./today";

const sample: readonly TodayEntry[] = [
  {
    id: "a",
    kind: "food",
    text: "Oatmeal",
    status: "complete",
    calories: 300,
    sourceBacked: true,
  },
  {
    id: "b",
    kind: "exercise",
    text: "Run",
    status: "complete",
    calories: 250,
    sourceBacked: false,
  },
  {
    id: "c",
    kind: "food",
    text: "Latte",
    status: "pending",
    calories: null,
    sourceBacked: null,
  },
];

describe("selectPending / selectComplete", () => {
  it("partitions entries by status", () => {
    expect(selectPending(sample).map((e) => e.id)).toEqual(["c"]);
    expect(selectComplete(sample).map((e) => e.id)).toEqual(["a", "b"]);
  });

  it("returns empty arrays when nothing matches", () => {
    expect(selectPending(selectComplete(sample))).toEqual([]);
  });
});

describe("summarizeDay", () => {
  it("rolls up completed food and exercise calories", () => {
    expect(summarizeDay(sample)).toEqual({
      pendingCount: 1,
      completeCount: 2,
      consumed: 300,
      burned: 250,
      net: 50,
    });
  });

  it("excludes pending entries from calorie totals", () => {
    const onlyPending: TodayEntry[] = [
      {
        id: "p",
        kind: "food",
        text: "TBD",
        status: "pending",
        calories: null,
        sourceBacked: null,
      },
    ];
    expect(summarizeDay(onlyPending)).toEqual({
      pendingCount: 1,
      completeCount: 0,
      consumed: 0,
      burned: 0,
      net: 0,
    });
  });

  it("handles an empty day", () => {
    expect(summarizeDay([])).toEqual({
      pendingCount: 0,
      completeCount: 0,
      consumed: 0,
      burned: 0,
      net: 0,
    });
  });
});

describe("statusAccessibilityLabel", () => {
  it("labels pending entries as estimating", () => {
    expect(statusAccessibilityLabel(sample[2])).toBe("Estimating");
  });

  it("distinguishes source-backed completed estimates", () => {
    expect(statusAccessibilityLabel(sample[0])).toBe(
      "Estimated from a source",
    );
    expect(statusAccessibilityLabel(sample[1])).toBe("Estimated");
  });
});

describe("MOCK_TODAY_ENTRIES", () => {
  it("includes both pending and completed entries", () => {
    expect(selectPending(MOCK_TODAY_ENTRIES).length).toBeGreaterThan(0);
    expect(selectComplete(MOCK_TODAY_ENTRIES).length).toBeGreaterThan(0);
  });
});
