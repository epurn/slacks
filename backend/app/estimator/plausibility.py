"""Deterministic parse-candidate plausibility validator (FTY-156).

A cheap, model-free guard that checks each ``ParsedCandidate``'s quantity against
coarse physical/serving sanity ranges and a known-unit vocabulary *before* the parse
is trusted downstream. It catches gross parse errors — "50 eggs", "5000 g single
serving", a quantity attached to an unknown/garbage unit — without any confidence
signal, complementing FTY-115/FTY-132's nutrition-facts gate (which bounds per-100g
energy/macros after source resolution at a later pipeline stage).

Trust boundary (``docs/security/security-baseline.md``): the model's parse output is
untrusted; an implausible candidate is routed to clarification (not persisted as a
resolved-path item). The clarification question is a bounded, sanitised string; the
raw candidate name is length-bounded by the schema (``MAX_NAME_LEN = 200``) and is
stored as data, never executed.

Design:
- All bounds are **generous, documented tunables** — set just above any realistic
  single-entry portion so a false reject of a large-but-real meal is effectively
  impossible (FTY-115 philosophy: bound just above the true max, not tight to typical).
- The fail-safe failure mode is *loose*: an over-generous bound lets an absurd parse
  through once; a too-tight bound falsely asks the user. The former is cheaper.
- An unknown/garbage unit with a large numeric amount cannot be trusted because the
  units determine the scale; food-specific count units that match the item name pass
  as the loose, low-false-reject default.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Final

from app.estimator.food_serving import HOUSEHOLD_VOLUME_UNIT_ML
from app.schemas.parse import ParsedCandidate

# ---------------------------------------------------------------------------
# Tunables — documented constants block (per FTY-042 precedent).
# Each bound has a rationale comment so reviewers and maintainers can judge
# whether a value should move.
# ---------------------------------------------------------------------------

#: Maximum realistic *generic discrete count* for a single logged entry.
#: Small foods can be logged one-by-one ("100 blueberries", "80 grapes", or a
#: large pile of crackers), so this global cap is deliberately loose.
#: Clearly large counted foods use the narrower override below.
MAX_PLAUSIBLE_COUNT: Final[float] = 250.0

#: Maximum realistic count for clearly large item words.
#: This intentionally starts narrow: it preserves the acceptance-criteria reject
#: for "50 eggs" without re-tightening the global cap for small foods.
MAX_PLAUSIBLE_LARGE_ITEM_COUNT: Final[float] = 36.0

#: Unknown units above this amount fail unless they look like a food-specific
#: count unit matching the item name (e.g. "50 crackers" as a unit on crackers).
#: This keeps garbage units such as "50 zxcv" from becoming plausible just
#: because the generic small-food count cap is loose.
MAX_PLAUSIBLE_UNKNOWN_UNIT_AMOUNT: Final[float] = 36.0

#: Maximum realistic *mass in grams* for a single logged entry.
#: The heaviest plausible single-sitting meal is a large restaurant steak + sides
#: (~800–900 g cooked). 2 000 g leaves generous room above that; 5 000 g
#: (the acceptance-criteria example) is well above.
MAX_PLAUSIBLE_GRAMS: Final[float] = 2000.0

#: Maximum realistic *volume in millilitres* for a single logged entry.
#: A large smoothie / a 1-litre water bottle is ~1 000 ml.
#: 2 000 ml (2 litres) leaves room for a very large hydration event.
MAX_PLAUSIBLE_ML: Final[float] = 2000.0

# ---------------------------------------------------------------------------
# Recognised unit vocabulary — split into three semantic families.
# A unit not in any family is "unknown/garbage" when a numeric amount is set,
# because the amount cannot be interpreted.
# ---------------------------------------------------------------------------

#: Mass units the validator recognises.  Mirrors food_serving._MASS_UNIT_GRAMS.
_MASS_UNITS: Final[frozenset[str]] = frozenset(
    {
        "mg",
        "g",
        "gram",
        "grams",
        "gm",
        "kg",
        "oz",
        "ounce",
        "ounces",
        "lb",
        "lbs",
        "pound",
        "pounds",
    }
)

#: Volume units the validator recognises.  Mirrors food_serving._VOLUME_UNIT_GRAMS.
_VOLUME_UNITS: Final[frozenset[str]] = frozenset(
    {
        "ml",
        "milliliter",
        "millilitre",
        "milliliters",
        "millilitres",
        "cc",
        "l",
        "liter",
        "litre",
        "liters",
        "litres",
        "fl",
        "floz",
        "fl_oz",
        "fluid_ounce",
        "fluid_ounces",
        "cup",
        "cups",
        "tbsp",
        "tbs",
        "tablespoon",
        "tablespoons",
        "tsp",
        "teaspoon",
        "teaspoons",
        "pint",
        "pints",
        "pt",
        "quart",
        "quarts",
        "qt",
        "gallon",
        "gallons",
        "gal",
    }
)

#: Count / portion-word units. Also covers the no-unit case (None / empty string).
_COUNT_UNITS: Final[frozenset[str]] = frozenset(
    {
        "",
        "x",
        "ct",
        "count",
        "serving",
        "servings",
        "piece",
        "pieces",
        "item",
        "items",
        "unit",
        "units",
        "portion",
        "portions",
        "slice",
        "slices",
        "strip",
        "strips",
        "sheet",
        "sheets",
        "whole",
        "half",
        "halves",
        "handful",
        "handfuls",
        "pinch",
        "pinches",
        "dash",
        "dashes",
        "drop",
        "drops",
        "clove",
        "cloves",
        "sprig",
        "sprigs",
        "leaf",
        "leaves",
        "stalk",
        "stalks",
        "stick",
        "sticks",
        "bar",
        "bars",
        "packet",
        "packets",
        "pack",
        "packs",
        "bag",
        "bags",
        "can",
        "cans",
        "jar",
        "jars",
        "bottle",
        "bottles",
        "glass",
        "glasses",
        "mug",
        "mugs",
        "bowl",
        "bowls",
        "plate",
        "plates",
        "scoop",
        "scoops",
        "dollop",
        "dollops",
        "drizzle",
        "drizzles",
        "splash",
        "splashes",
    }
)

# Gram equivalents for mass units, used to convert to grams for the mass cap check.
_MASS_UNIT_GRAMS: Final[dict[str, float]] = {
    "mg": 0.001,
    "g": 1.0,
    "gram": 1.0,
    "grams": 1.0,
    "gm": 1.0,
    "kg": 1000.0,
    "oz": 28.349523125,
    "ounce": 28.349523125,
    "ounces": 28.349523125,
    "lb": 453.59237,
    "lbs": 453.59237,
    "pound": 453.59237,
    "pounds": 453.59237,
}

# Millilitre equivalents for volume units, used to convert to ml for the volume cap.
# The household measures (cup/tsp/tbsp/fl oz/pint/quart/gallon) derive from the
# single shared ``HOUSEHOLD_VOLUME_UNIT_ML`` table (FTY-276) that
# ``app.estimator.food_serving`` also consumes for its grams conversions, so the
# two can no longer silently diverge. This shifts the volume cap by <2% from the
# previous exact US-customary values here — immaterial to this validator's coarse
# volume cap (FTY-275 author note, 2026-07-07).
_VOLUME_UNIT_ML: Final[dict[str, float]] = {
    "ml": 1.0,
    "milliliter": 1.0,
    "millilitre": 1.0,
    "milliliters": 1.0,
    "millilitres": 1.0,
    "cc": 1.0,
    "l": 1000.0,
    "liter": 1000.0,
    "litre": 1000.0,
    "liters": 1000.0,
    "litres": 1000.0,
    "fl": HOUSEHOLD_VOLUME_UNIT_ML["fl_oz"],
    "floz": HOUSEHOLD_VOLUME_UNIT_ML["fl_oz"],
    "fl_oz": HOUSEHOLD_VOLUME_UNIT_ML["fl_oz"],
    "fluid_ounce": HOUSEHOLD_VOLUME_UNIT_ML["fl_oz"],
    "fluid_ounces": HOUSEHOLD_VOLUME_UNIT_ML["fl_oz"],
    "cup": HOUSEHOLD_VOLUME_UNIT_ML["cup"],
    "cups": HOUSEHOLD_VOLUME_UNIT_ML["cup"],
    "tbsp": HOUSEHOLD_VOLUME_UNIT_ML["tbsp"],
    "tbs": HOUSEHOLD_VOLUME_UNIT_ML["tbsp"],
    "tablespoon": HOUSEHOLD_VOLUME_UNIT_ML["tbsp"],
    "tablespoons": HOUSEHOLD_VOLUME_UNIT_ML["tbsp"],
    "tsp": HOUSEHOLD_VOLUME_UNIT_ML["tsp"],
    "teaspoon": HOUSEHOLD_VOLUME_UNIT_ML["tsp"],
    "teaspoons": HOUSEHOLD_VOLUME_UNIT_ML["tsp"],
    "pint": HOUSEHOLD_VOLUME_UNIT_ML["pint"],
    "pints": HOUSEHOLD_VOLUME_UNIT_ML["pint"],
    "pt": HOUSEHOLD_VOLUME_UNIT_ML["pint"],
    "quart": HOUSEHOLD_VOLUME_UNIT_ML["quart"],
    "quarts": HOUSEHOLD_VOLUME_UNIT_ML["quart"],
    "qt": HOUSEHOLD_VOLUME_UNIT_ML["quart"],
    "gallon": HOUSEHOLD_VOLUME_UNIT_ML["gallon"],
    "gallons": HOUSEHOLD_VOLUME_UNIT_ML["gallon"],
    "gal": HOUSEHOLD_VOLUME_UNIT_ML["gallon"],
}

# Match a bounded explicit "<number> <mass|volume unit>" phrase in quantity_text.
# The parse schema bounds quantity_text to 120 chars, so scanning is deterministic
# and cheap.
_QUANTITY_TEXT_MEASURE_RE: Final[re.Pattern[str]] = re.compile(
    r"(?<![0-9A-Za-z.])(\d+(?:,\d{3})*(?:\.\d+)?)\s*([A-Za-z_]+)\b"
)

_WORD_RE: Final[re.Pattern[str]] = re.compile(r"[a-z]+")

_LARGE_COUNT_ITEM_WORDS: Final[frozenset[str]] = frozenset({"egg"})

_ALL_KNOWN_UNITS: Final[frozenset[str]] = _MASS_UNITS | _VOLUME_UNITS | _COUNT_UNITS


@dataclass(frozen=True)
class PlausibilityResult:
    """Outcome of a single-candidate plausibility check.

    ``plausible`` is ``True`` when the candidate passes all gates. When
    ``False``, ``reason`` is a short sanitised label (never raw user text) and
    ``clarification_question`` is a bounded, human-readable question naming the
    item that was implausible (safe to present to the user).
    """

    plausible: bool
    #: Short label for the failure mode; ``None`` when ``plausible`` is ``True``.
    reason: str | None = None
    #: Question to surface to the user; ``None`` when ``plausible`` is ``True``.
    clarification_question: str | None = None


def check_candidate(candidate: ParsedCandidate) -> PlausibilityResult:  # noqa: PLR0911 — many guards
    """Return whether ``candidate``'s quantity is physically plausible.

    Rules (generous, documented tunables — see module-level constants):

    1. **Negative / non-finite amount → fail.**  The schema already enforces
       ``amount >= 0`` via Pydantic, but NaN/inf can reach a ``float`` field in
       some serialisation paths (JSON ``Infinity``); gate defensively.
    2. **Unknown/garbage unit with a large numeric amount → fail.**  A unit not
       in the recognised vocabulary is treated as a possible food-specific count
       only when it matches the item name; otherwise a large unknown-unit amount
       is too ambiguous to trust.
    3. **Implausible count → fail.**  A discrete count above the applicable count
       cap is beyond any realistic single-entry portion. The generic cap is loose
       for small foods; clearly large counted items use a narrower cap.
    4. **Implausible mass → fail.**  A mass that converts to more than
       ``MAX_PLAUSIBLE_GRAMS`` grams is beyond any realistic single-entry portion.
    5. **Implausible volume → fail.**  A volume that converts to more than
       ``MAX_PLAUSIBLE_ML`` ml is beyond any realistic single-entry portion.

    Every explicit mass/volume measure in ``quantity_text`` is checked against the
    same bounds, even when the model also supplied a structured count/portion
    amount. A candidate with no structured ``amount`` and no explicit mass/volume
    measure in ``quantity_text`` is considered plausible; quantity inference
    failures are handled by the confidence/disposition check upstream.
    """

    amount = candidate.amount
    normalized_unit = (candidate.unit or "").strip().lower()

    # Rule 1: negative or non-finite amount (schema guards ge=0, but guard NaN/inf).
    if amount is not None and (not math.isfinite(amount) or amount < 0):
        return PlausibilityResult(
            plausible=False,
            reason="non_finite_or_negative_amount",
            clarification_question=_question(candidate.name, "amount"),
        )

    measure_failure = _quantity_text_measure_failure(candidate)
    if measure_failure is not None:
        return measure_failure

    if amount is None:
        # No amount and no implausible explicit text measure: nothing else to validate here.
        return PlausibilityResult(plausible=True)

    # Rule 2: unknown/garbage unit with a numeric amount.
    # "Normalise away" interpretation: a unit not in any recognised family can
    # be a food-specific count (e.g. "crackers" used as the count unit for a
    # cracker entry). Treat name-matching units as counts and keep unrelated
    # unknown units on the conservative garbage-unit threshold.
    if candidate.unit is not None and normalized_unit not in _ALL_KNOWN_UNITS:
        if _looks_like_food_specific_count_unit(candidate.name, normalized_unit):
            count_cap = _count_cap(candidate, normalized_unit)
            if amount > count_cap:
                return PlausibilityResult(
                    plausible=False,
                    reason="implausible_count",
                    clarification_question=_question(candidate.name, "count"),
                )
            return PlausibilityResult(plausible=True)

        if amount > MAX_PLAUSIBLE_UNKNOWN_UNIT_AMOUNT:
            return PlausibilityResult(
                plausible=False,
                reason="unknown_unit",
                clarification_question=_question(candidate.name, "unit"),
            )
        # Amount is within the conservative unknown-unit amount range; pass as
        # the loose/safe failure mode for odd but small food-specific units.
        return PlausibilityResult(plausible=True)

    # Rule 3: implausible count.
    if normalized_unit in _COUNT_UNITS and amount > _count_cap(candidate, normalized_unit):
        return PlausibilityResult(
            plausible=False,
            reason="implausible_count",
            clarification_question=_question(candidate.name, "count"),
        )

    # Rule 4: implausible mass.
    measure_failure = _measured_quantity_failure(candidate, amount, normalized_unit)
    if measure_failure is not None:
        return measure_failure

    # Rule 5: implausible volume.
    # Covered by _measured_quantity_failure above.
    return PlausibilityResult(plausible=True)


def _measured_quantity_failure(
    candidate: ParsedCandidate, amount: float, normalized_unit: str
) -> PlausibilityResult | None:
    """Return a mass/volume bound failure for ``amount`` + ``normalized_unit``, if any."""

    grams_per_unit = _MASS_UNIT_GRAMS.get(normalized_unit)
    if grams_per_unit is not None:
        mass_g = amount * grams_per_unit
        if mass_g > MAX_PLAUSIBLE_GRAMS:
            return PlausibilityResult(
                plausible=False,
                reason="implausible_mass",
                clarification_question=_question(candidate.name, "amount"),
            )

    ml_per_unit = _VOLUME_UNIT_ML.get(normalized_unit)
    if ml_per_unit is not None:
        volume_ml = amount * ml_per_unit
        if volume_ml > MAX_PLAUSIBLE_ML:
            return PlausibilityResult(
                plausible=False,
                reason="implausible_volume",
                clarification_question=_question(candidate.name, "amount"),
            )

    return None


def _quantity_text_measure_failure(candidate: ParsedCandidate) -> PlausibilityResult | None:
    """Return the first mass/volume bound failure found in ``candidate.quantity_text``.

    This is a validation signal only: it does not normalise or persist the
    candidate. It closes the bypass where the raw portion phrase still carries a
    concrete measured quantity such as ``5000g`` even when structured fields are
    missing or describe only a count/portion.
    """

    for match in _QUANTITY_TEXT_MEASURE_RE.finditer(candidate.quantity_text):
        normalized_unit = match.group(2).lower()
        if normalized_unit not in _MASS_UNIT_GRAMS and normalized_unit not in _VOLUME_UNIT_ML:
            continue
        amount = float(match.group(1).replace(",", ""))
        if amount > 0 and math.isfinite(amount):
            measure_failure = _measured_quantity_failure(candidate, amount, normalized_unit)
            if measure_failure is not None:
                return measure_failure
    return None


def _count_cap(candidate: ParsedCandidate, normalized_unit: str) -> float:
    """Return the count cap for ``candidate`` after item-size overrides."""

    if _uses_large_item_count_cap(candidate.name, normalized_unit):
        return MAX_PLAUSIBLE_LARGE_ITEM_COUNT
    return MAX_PLAUSIBLE_COUNT


def _uses_large_item_count_cap(item_name: str, normalized_unit: str) -> bool:
    """Return whether count bounds should use the narrow large-item cap."""

    unit_stems = _word_stems(normalized_unit)
    if unit_stems & _LARGE_COUNT_ITEM_WORDS:
        return True

    last_name_word = _last_word_stem(item_name)
    return last_name_word in _LARGE_COUNT_ITEM_WORDS


def _looks_like_food_specific_count_unit(item_name: str, normalized_unit: str) -> bool:
    """Return whether an unknown unit appears to name the item being counted."""

    unit_stems = _word_stems(normalized_unit)
    if not unit_stems:
        return False
    return unit_stems <= _word_stems(item_name)


def _word_stems(text: str) -> frozenset[str]:
    """Return simple lower-case singular-ish stems for count-word comparison."""

    return frozenset(_count_word_stem(word) for word in _WORD_RE.findall(text.lower()))


def _last_word_stem(text: str) -> str:
    """Return the simple stem of the last word in ``text``."""

    words = _WORD_RE.findall(text.lower())
    if not words:
        return ""
    return _count_word_stem(words[-1])


#: Shortest word longer than the ``ies`` suffix itself, so ``word[:-3]`` keeps at
#: least one stem character (e.g. "pies" -> "py", but "ies" is left untouched).
_MIN_IES_STEM_LEN = 3


def _count_word_stem(word: str) -> str:
    """Return a small plural-normalised form for food count terms."""

    if len(word) > _MIN_IES_STEM_LEN and word.endswith("ies"):
        return f"{word[:-3]}y"
    if len(word) > 1 and word.endswith("s"):
        return word[:-1]
    return word


def _question(item_name: str, mode: str) -> str:
    """Return a sanitised clarification question naming the implausible item.

    The item name comes from the schema-validated ``ParsedCandidate.name``, which is
    bounded to ``MAX_NAME_LEN = 200`` characters and stored as data — never executed.
    The question interpolates only that bounded name into a fixed template; it never
    echoes the raw log text or any unbounded model output.
    """

    if mode == "unit":
        return f"What unit were you using for {item_name}?"
    if mode == "count":
        return f"How many {item_name} did you have?"
    return f"How much {item_name} did you have?"
