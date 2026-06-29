import {
  METABOLIC_FORMULA_OPTIONS,
  cmToMeters,
  emptyProfileForm,
  feetInchesToMeters,
  metersToFeetInches,
  kilograms,
  poundsToKilograms,
  validateProfileForm,
  type ProfileFormState,
} from "./profile";

const CURRENT_YEAR = 2026;

/** A fully valid metric form, overridable per test. */
function metricForm(overrides: Partial<ProfileFormState> = {}): ProfileFormState {
  return {
    ...emptyProfileForm("metric", "America/New_York"),
    heightCm: "175",
    weight: "70",
    birthYear: "1990",
    metabolicFormula: "mifflin_st_jeor_plus5",
    ...overrides,
  };
}

describe("unit conversions", () => {
  it("converts centimetres to metres", () => {
    expect(cmToMeters(175)).toBe(1.75);
    expect(cmToMeters(180.3)).toBe(1.803);
  });

  it("converts feet and inches to metres", () => {
    // 5 ft 9 in ≈ 1.7526 m
    expect(feetInchesToMeters(5, 9)).toBeCloseTo(1.7526, 3);
    // 6 ft 0 in = 1.8288 m
    expect(feetInchesToMeters(6, 0)).toBeCloseTo(1.8288, 3);
  });

  it("converts pounds to kilograms", () => {
    expect(poundsToKilograms(154)).toBeCloseTo(69.85, 2);
    expect(poundsToKilograms(200)).toBeCloseTo(90.718, 2);
  });

  it("passes kilograms through with canonical rounding", () => {
    expect(kilograms(70.4567)).toBe(70.457);
  });

  it("splits metres into whole feet + inches", () => {
    expect(metersToFeetInches(1.7526)).toEqual({ feet: 5, inches: 9 });
    expect(metersToFeetInches(1.8288)).toEqual({ feet: 6, inches: 0 });
  });

  it("never yields a rounded-up '12 in' at a foot boundary", () => {
    // ~71.6 in rounds to 72 in → 6 ft 0 in, never 5 ft 12 in.
    const { feet, inches } = metersToFeetInches(1.8186);
    expect(inches).toBeLessThan(12);
    expect({ feet, inches }).toEqual({ feet: 6, inches: 0 });
  });
});

describe("metabolic formula options", () => {
  it("offers exactly the two MSJ variants, no clinical placeholder", () => {
    expect(METABOLIC_FORMULA_OPTIONS.map((o) => o.value)).toEqual([
      "mifflin_st_jeor_plus5",
      "mifflin_st_jeor_minus161",
    ]);
  });

  it("uses non-clinical labels (no biological-sex wording)", () => {
    const text = METABOLIC_FORMULA_OPTIONS.map(
      (o) => `${o.label} ${o.description}`,
    )
      .join(" ")
      .toLowerCase();
    expect(text).not.toContain("sex");
    expect(text).not.toContain("male");
    expect(text).not.toContain("female");
    expect(text).not.toContain("gender");
  });
});

describe("validateProfileForm — success", () => {
  it("builds a canonical payload from metric input", () => {
    const result = validateProfileForm(metricForm(), CURRENT_YEAR);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.payload).toEqual({
      height_m: 1.75,
      weight_kg: 70,
      birth_year: 1990,
      metabolic_formula: "mifflin_st_jeor_plus5",
      units_preference: "metric",
      timezone: "America/New_York",
    });
  });

  it("converts imperial input to canonical metres and kilograms", () => {
    const form: ProfileFormState = {
      ...emptyProfileForm("imperial", "America/Los_Angeles"),
      heightFeet: "5",
      heightInches: "9",
      weight: "154",
      birthYear: "1985",
      metabolicFormula: "mifflin_st_jeor_minus161",
    };
    const result = validateProfileForm(form, CURRENT_YEAR);
    expect(result.ok).toBe(true);
    if (!result.ok) return;
    expect(result.payload.height_m).toBeCloseTo(1.7526, 3);
    expect(result.payload.weight_kg).toBeCloseTo(69.85, 2);
    expect(result.payload.units_preference).toBe("imperial");
    expect(result.payload.metabolic_formula).toBe("mifflin_st_jeor_minus161");
  });
});

describe("validateProfileForm — validation", () => {
  it("requires every field with nonjudgmental messages", () => {
    const result = validateProfileForm(
      emptyProfileForm("metric", "UTC"),
      CURRENT_YEAR,
    );
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.height).toBeDefined();
    expect(result.errors.weight).toBeDefined();
    expect(result.errors.birthYear).toBeDefined();
    expect(result.errors.metabolicFormula).toBeDefined();
    // Messages should not shame the user about their body.
    const all = Object.values(result.errors).join(" ").toLowerCase();
    expect(all).not.toContain("invalid");
    expect(all).not.toContain("too");
  });

  it("rejects an implausibly large height", () => {
    const result = validateProfileForm(
      metricForm({ heightCm: "400" }),
      CURRENT_YEAR,
    );
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.height).toBeDefined();
  });

  it("rejects an implausibly small weight", () => {
    const result = validateProfileForm(
      metricForm({ weight: "0.5" }),
      CURRENT_YEAR,
    );
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.weight).toBeDefined();
  });

  it("rejects a future or non-integer birth year", () => {
    expect(
      validateProfileForm(metricForm({ birthYear: "2099" }), CURRENT_YEAR).ok,
    ).toBe(false);
    expect(
      validateProfileForm(metricForm({ birthYear: "19.9" }), CURRENT_YEAR).ok,
    ).toBe(false);
    expect(
      validateProfileForm(metricForm({ birthYear: "1850" }), CURRENT_YEAR).ok,
    ).toBe(false);
  });

  it("requires a metabolic formula choice", () => {
    const result = validateProfileForm(
      metricForm({ metabolicFormula: null }),
      CURRENT_YEAR,
    );
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.metabolicFormula).toBeDefined();
  });

  it("rejects out-of-range imperial inches", () => {
    const result = validateProfileForm(
      {
        ...emptyProfileForm("imperial", "UTC"),
        heightFeet: "5",
        heightInches: "15",
        weight: "150",
        birthYear: "1990",
        metabolicFormula: "mifflin_st_jeor_plus5",
      },
      CURRENT_YEAR,
    );
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.height).toBeDefined();
  });

  it("rejects a blank timezone", () => {
    const result = validateProfileForm(
      metricForm({ timezone: "   " }),
      CURRENT_YEAR,
    );
    expect(result.ok).toBe(false);
    if (result.ok) return;
    expect(result.errors.timezone).toBeDefined();
  });
});
