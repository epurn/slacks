import {
  formatDate,
  kgToDisplay,
  parseWeightInput,
  subtractDays,
  weightUnitLabel,
} from "./weightEntries";

describe("weightUnitLabel", () => {
  it("returns kg for metric", () => {
    expect(weightUnitLabel("metric")).toBe("kg");
  });

  it("returns lb for imperial", () => {
    expect(weightUnitLabel("imperial")).toBe("lb");
  });
});

describe("kgToDisplay", () => {
  it("returns kg rounded to 1 decimal for metric", () => {
    expect(kgToDisplay(70.123, "metric")).toBe(70.1);
  });

  it("converts kg to lb and rounds to 1 decimal for imperial", () => {
    // 70 kg ÷ 0.45359237 ≈ 154.3 lb
    const result = kgToDisplay(70, "imperial");
    expect(result).toBeCloseTo(154.3, 0);
  });

  it("conversion factor matches NIST (1 lb = 0.45359237 kg)", () => {
    // 1 lb round-trip: kgToDisplay(0.45359237 kg, imperial) ≈ 1.0 lb
    expect(kgToDisplay(0.45359237, "imperial")).toBeCloseTo(1.0, 1);
  });
});

describe("parseWeightInput", () => {
  it("returns the parsed number for a valid positive decimal", () => {
    expect(parseWeightInput("70.5")).toBe(70.5);
  });

  it("returns null for an empty string", () => {
    expect(parseWeightInput("")).toBeNull();
  });

  it("returns null for whitespace only", () => {
    expect(parseWeightInput("   ")).toBeNull();
  });

  it("returns null for zero", () => {
    expect(parseWeightInput("0")).toBeNull();
  });

  it("returns null for a negative value", () => {
    expect(parseWeightInput("-5")).toBeNull();
  });

  it("returns null for non-numeric text", () => {
    expect(parseWeightInput("abc")).toBeNull();
  });

  it("trims whitespace before parsing", () => {
    expect(parseWeightInput("  80  ")).toBe(80);
  });
});

describe("formatDate", () => {
  it("formats a date as YYYY-MM-DD", () => {
    // Use local-time constructor to avoid UTC-offset day-boundary issues.
    expect(formatDate(new Date(2026, 5, 27))).toBe("2026-06-27");
  });

  it("zero-pads single-digit month and day", () => {
    // Use local date constructor to avoid UTC vs local offset issues in tests
    const d = new Date(2026, 0, 5); // Jan 5
    expect(formatDate(d)).toBe("2026-01-05");
  });
});

describe("subtractDays", () => {
  it("subtracts the given number of days from the date", () => {
    const from = new Date(2026, 5, 27); // June 27
    const result = subtractDays(from, 90);
    expect(formatDate(result)).toBe("2026-03-29");
  });

  it("does not mutate the input date", () => {
    const from = new Date(2026, 5, 27);
    subtractDays(from, 10);
    expect(formatDate(from)).toBe("2026-06-27");
  });
});
