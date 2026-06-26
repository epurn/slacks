/**
 * Profile capture domain logic for the minimal required profile (FTY-021).
 *
 * This module owns the *pure* parts of the capture flow so they are fully unit
 * testable without rendering or networking: the field vocabulary, unit
 * conversion to canonical units (metres, kilograms), client-side validation
 * with nonjudgmental messages, and assembly of the canonical update payload
 * sent to the FTY-020 profile API.
 *
 * Canonical units mirror the persistence contract (`docs/contracts/
 * identity-and-profile.md`): the API only ever stores `height_m` in metres and
 * `weight_kg` in kilograms. `unitsPreference` is a display choice and never
 * changes what is stored — imperial input is converted here before it leaves
 * the device.
 */

/**
 * Metabolic-formula preference the capture UI offers. These are the two
 * Mifflin-St Jeor variants that carry the formula's sex-dependent additive
 * constant; the user picks one as a *calculation* preference, framed without
 * clinical "biological sex" wording (see the option metadata below). The values
 * match the FTY-020 `metabolic_formula` contract vocabulary and the constants
 * FTY-022's RMR calculator maps them to. The family placeholder
 * (`mifflin_st_jeor`) is intentionally not offered: it carries no constant.
 */
export type MetabolicFormula =
  | "mifflin_st_jeor_plus5"
  | "mifflin_st_jeor_minus161";

/** Display-unit preference. Storage is always canonical (kg, m). */
export type UnitsPreference = "metric" | "imperial";

/**
 * A selectable metabolic-formula option: its contract value plus the
 * non-clinical, calculation-framed copy shown to the user.
 *
 * NOTE: the exact user-facing strings are product-polish copy (the story flags
 * them as refinable in review). The hard constraint met here is that the
 * wording is non-clinical and maps unambiguously to one MSJ constant; `+5`
 * yields a higher resting estimate than `-161`, hence the "higher/lower
 * baseline" framing, with the constant shown so the mapping is unambiguous.
 */
export interface MetabolicFormulaOption {
  readonly value: MetabolicFormula;
  readonly label: string;
  readonly description: string;
}

/** The two MSJ variants offered as a required, mutually exclusive choice. */
export const METABOLIC_FORMULA_OPTIONS: readonly MetabolicFormulaOption[] = [
  {
    value: "mifflin_st_jeor_plus5",
    label: "Higher baseline (+5)",
    description:
      "Mifflin-St Jeor with the +5 constant — a higher resting estimate.",
  },
  {
    value: "mifflin_st_jeor_minus161",
    label: "Lower baseline (−161)",
    description:
      "Mifflin-St Jeor with the −161 constant — a lower resting estimate.",
  },
];

/** Plausible canonical ranges. Mirror the FTY-020 bounds, tightened for input. */
export const HEIGHT_M_RANGE = { min: 0.5, max: 2.72 } as const;
export const WEIGHT_KG_RANGE = { min: 2, max: 650 } as const;
/** Earliest plausible birth year; the latest is the current year (injected). */
export const MIN_BIRTH_YEAR = 1900;

// Exact conversion factors (international definitions).
const CM_PER_M = 100;
const INCH_PER_M = 39.37007874015748; // 1 m / 0.0254 m-per-inch
const INCH_PER_FOOT = 12;
const KG_PER_LB = 0.45359237;

/** Round to a fixed number of decimals to keep canonical payloads tidy. */
function round(value: number, decimals: number): number {
  const factor = 10 ** decimals;
  return Math.round(value * factor) / factor;
}

/** Centimetres → metres. */
export function cmToMeters(cm: number): number {
  return round(cm / CM_PER_M, 4);
}

/** Feet + inches → metres. */
export function feetInchesToMeters(feet: number, inches: number): number {
  const totalInches = feet * INCH_PER_FOOT + inches;
  return round(totalInches / INCH_PER_M, 4);
}

/** Pounds → kilograms. */
export function poundsToKilograms(pounds: number): number {
  return round(pounds * KG_PER_LB, 3);
}

/** Kilograms passthrough with canonical rounding. */
export function kilograms(kg: number): number {
  return round(kg, 3);
}

/**
 * Raw form state. Numeric fields are strings because they come from text
 * inputs; validation parses and range-checks them. Height has two shapes
 * depending on the units preference.
 */
export interface ProfileFormState {
  readonly unitsPreference: UnitsPreference;
  /** Metric height in centimetres (used when `unitsPreference === "metric"`). */
  readonly heightCm: string;
  /** Imperial height feet (used when `unitsPreference === "imperial"`). */
  readonly heightFeet: string;
  /** Imperial height inches (used when `unitsPreference === "imperial"`). */
  readonly heightInches: string;
  /** Weight in kg (metric) or lb (imperial). */
  readonly weight: string;
  readonly birthYear: string;
  readonly metabolicFormula: MetabolicFormula | null;
  /** IANA timezone name (defaulted from the device, confirmable by the user). */
  readonly timezone: string;
}

/** An empty form seeded with the device's units and timezone. */
export function emptyProfileForm(
  unitsPreference: UnitsPreference,
  timezone: string,
): ProfileFormState {
  return {
    unitsPreference,
    heightCm: "",
    heightFeet: "",
    heightInches: "",
    weight: "",
    birthYear: "",
    metabolicFormula: null,
    timezone,
  };
}

/**
 * Canonical update payload — exactly the FTY-020 `ProfileUpdateRequest` shape.
 * All required capture fields are present (this flow captures the full minimal
 * profile at once), in canonical units.
 */
export interface ProfileUpdatePayload {
  readonly height_m: number;
  readonly weight_kg: number;
  readonly birth_year: number;
  readonly metabolic_formula: MetabolicFormula;
  readonly units_preference: UnitsPreference;
  readonly timezone: string;
}

/** Field-keyed validation errors. A present key means that field is invalid. */
export type ProfileFormErrors = Partial<
  Record<
    "height" | "weight" | "birthYear" | "metabolicFormula" | "timezone",
    string
  >
>;

export type ProfileValidationResult =
  | { readonly ok: true; readonly payload: ProfileUpdatePayload }
  | { readonly ok: false; readonly errors: ProfileFormErrors };

/** Parse a trimmed, finite number, or `null` if the text is not a number. */
function parseNumber(text: string): number | null {
  const trimmed = text.trim();
  if (trimmed === "") {
    return null;
  }
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : null;
}

function validateHeight(
  form: ProfileFormState,
  errors: ProfileFormErrors,
): number | null {
  let meters: number | null = null;
  if (form.unitsPreference === "metric") {
    const cm = parseNumber(form.heightCm);
    if (cm === null) {
      errors.height = "Enter your height in centimetres.";
      return null;
    }
    meters = cmToMeters(cm);
  } else {
    const feet = parseNumber(form.heightFeet);
    const inches = parseNumber(form.heightInches) ?? 0;
    if (feet === null) {
      errors.height = "Enter your height in feet and inches.";
      return null;
    }
    if (inches < 0 || inches >= INCH_PER_FOOT) {
      errors.height = "Inches should be between 0 and 11.";
      return null;
    }
    meters = feetInchesToMeters(feet, inches);
  }
  if (meters < HEIGHT_M_RANGE.min || meters > HEIGHT_M_RANGE.max) {
    errors.height = "That height looks off — double-check and try again.";
    return null;
  }
  return meters;
}

function validateWeight(
  form: ProfileFormState,
  errors: ProfileFormErrors,
): number | null {
  const entered = parseNumber(form.weight);
  if (entered === null) {
    errors.weight =
      form.unitsPreference === "metric"
        ? "Enter your weight in kilograms."
        : "Enter your weight in pounds.";
    return null;
  }
  const kg =
    form.unitsPreference === "metric"
      ? kilograms(entered)
      : poundsToKilograms(entered);
  if (kg < WEIGHT_KG_RANGE.min || kg > WEIGHT_KG_RANGE.max) {
    errors.weight = "That weight looks off — double-check and try again.";
    return null;
  }
  return kg;
}

function validateBirthYear(
  form: ProfileFormState,
  currentYear: number,
  errors: ProfileFormErrors,
): number | null {
  const year = parseNumber(form.birthYear);
  if (year === null || !Number.isInteger(year)) {
    errors.birthYear = "Enter your birth year, e.g. 1990.";
    return null;
  }
  if (year < MIN_BIRTH_YEAR || year > currentYear) {
    errors.birthYear = `Enter a birth year between ${MIN_BIRTH_YEAR} and ${currentYear}.`;
    return null;
  }
  return year;
}

/**
 * Validate the form and, when every field is valid, produce the canonical
 * payload. `currentYear` is injected so this stays pure and deterministic.
 *
 * Messages are deliberately plain and nonjudgmental: they say what to enter,
 * not that the user got something "wrong" about their body.
 */
export function validateProfileForm(
  form: ProfileFormState,
  currentYear: number,
): ProfileValidationResult {
  const errors: ProfileFormErrors = {};

  const height_m = validateHeight(form, errors);
  const weight_kg = validateWeight(form, errors);
  const birth_year = validateBirthYear(form, currentYear, errors);

  if (form.metabolicFormula === null) {
    errors.metabolicFormula = "Choose a calculation preference to continue.";
  }

  const timezone = form.timezone.trim();
  if (timezone === "") {
    errors.timezone = "A timezone is required.";
  }

  if (
    height_m === null ||
    weight_kg === null ||
    birth_year === null ||
    form.metabolicFormula === null ||
    timezone === ""
  ) {
    return { ok: false, errors };
  }

  return {
    ok: true,
    payload: {
      height_m,
      weight_kg,
      birth_year,
      metabolic_formula: form.metabolicFormula,
      units_preference: form.unitsPreference,
      timezone,
    },
  };
}
