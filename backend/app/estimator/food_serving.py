"""Deterministic generic-food serving math (FTY-044).

Pure functions, no I/O, no LLM: a candidate's quantity (the parse step's
``unit`` / ``amount`` / ``quantity_text``) plus a per-100g nutrition fact sheet in,
canonical calories and macros out. This module owns two deterministic rules:

1. **quantity → grams** (:func:`resolve_grams`) — the v1-simple resolution the story
   scopes: an explicit mass (grams), a volume (millilitres, treated 1 ml ≈ 1 g),
   or a *count* multiplied by the source's default serving size. A quantity that
   cannot be resolved to grams confidently returns ``None`` so the caller routes to
   ``needs_clarification`` rather than guessing.
2. **grams → calories/macros** (:func:`scale_facts`) — scale canonical per-100g
   facts by the resolved grams, rounded to 0.1.

Storage is always canonical (kcal, grams); display units are a user preference,
handled elsewhere. Richer portion inference (``portion_memories``) is a later story.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Final

#: Physical maximum energy density of any real food (pure fat ≈ 9 kcal/g × 100 g).
#: Set conservatively just above the true maximum (~884 kcal/100g for pure oils) so
#: every legitimate food passes and a kJ-mislabelled value (~4× higher) is caught.
_MAX_ENERGY_KCAL_PER_100G: Final[float] = 900.0

#: Grams per recognised **mass** unit. The canonical storage unit is the gram.
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

#: Grams per recognised **volume** unit, under the documented v1 assumption that
#: 1 millilitre of a generic food weighs ~1 gram (water density). Refining this per
#: food density is out of scope for v1.
_VOLUME_UNIT_GRAMS: Final[dict[str, float]] = {
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
}

#: Unit phrases that denote a **count of servings** rather than a measured amount.
#: ``None`` (no unit) is also treated as a count. Resolved via the source's default
#: serving size, so a count is only resolvable when that serving size is known.
#:
#: Beyond the bare count words, this includes the common serving/portion nouns a
#: casual log uses (slice, sandwich, handful, ring, finger, bowl, …) so a
#: detail-rich generic entry — "a slice of pizza", "3 cracker sandwiches", "a
#: handful of onion rings" — resolves its portion via the default serving size
#: instead of stopping at clarification (FTY-167). This vocabulary is a superset
#: of the plausibility validator's ``_COUNT_UNITS``: food nouns such as sandwich/
#: ring/finger are accepted there via its name-match heuristic or its bounded
#: unknown-unit allowance, not by sharing this list.
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
        "sandwich",
        "sandwiches",
        "handful",
        "handfuls",
        "ring",
        "rings",
        "finger",
        "fingers",
        "strip",
        "strips",
        "stick",
        "sticks",
        "bar",
        "bars",
        "scoop",
        "scoops",
        "bowl",
        "bowls",
        "plate",
        "plates",
        "cracker",
        "crackers",
    }
)

#: Match a leading "<number> <unit>" inside a free-text quantity phrase ("150 g",
#: "2 cups"-style won't match a known unit and falls through). Used only when the
#: structured ``unit``/``amount`` did not already give a measured quantity.
_QUANTITY_TEXT_RE: Final[re.Pattern[str]] = re.compile(
    r"(\d+(?:\.\d+)?)\s*([a-zA-Z]+)",
)


@dataclass(frozen=True)
class NutritionFacts:
    """Canonical per-100g nutrition facts for a generic food.

    All four fields are per 100 grams in canonical units: ``calories`` in kcal,
    macros in grams. This is the deterministic input the serving math scales — never
    an LLM-supplied number; it comes from a trusted nutrition database (USDA FDC).
    """

    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


@dataclass(frozen=True)
class ScaledNutrition:
    """Calories and macros for a concrete portion, in canonical units.

    ``grams`` is the resolved portion mass the facts were scaled by; ``calories`` is
    kcal and the macros are grams, each rounded to 0.1.
    """

    grams: float
    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


def _normalize_unit(unit: str | None) -> str:
    """Lower-case and strip a unit token; ``None`` becomes the empty (count) token."""

    return (unit or "").strip().lower()


def resolve_grams(
    *,
    unit: str | None,
    amount: float | None,
    quantity_text: str,
    default_serving_g: float | None,
) -> float | None:
    """Resolve a candidate's quantity to grams, or ``None`` if not confidently possible.

    Resolution order (v1-simple, per the story scope):

    1. A structured ``amount`` with a recognised **mass** unit → grams directly.
    2. A structured ``amount`` with a recognised **volume** unit → grams at 1 ml ≈ 1 g.
    3. A structured ``amount`` with a **count** unit (or no unit) → ``amount ×
       default_serving_g`` when the source supplies a default serving size.
    4. Otherwise, scan ``quantity_text`` for a leading "<number> <mass|volume unit>".

    Returns ``None`` when none of these apply (e.g. a count with no known serving
    size, or an unrecognised/absent quantity), so the caller fails closed.
    """

    normalized = _normalize_unit(unit)

    if amount is not None and amount > 0:
        grams = _grams_from_measure(normalized, amount)
        if grams is not None:
            return grams
        if normalized in _COUNT_UNITS and default_serving_g is not None and default_serving_g > 0:
            return round(amount * default_serving_g, 3)

    return _grams_from_text(quantity_text)


def _grams_from_measure(normalized_unit: str, amount: float) -> float | None:
    """Grams for a measured (mass or volume) unit, or ``None`` for a non-measure unit."""

    mass = _MASS_UNIT_GRAMS.get(normalized_unit)
    if mass is not None:
        return round(amount * mass, 3)
    volume = _VOLUME_UNIT_GRAMS.get(normalized_unit)
    if volume is not None:
        return round(amount * volume, 3)
    return None


def _grams_from_text(quantity_text: str) -> float | None:
    """Best-effort grams from a "<number> <unit>" phrase; only mass/volume units count."""

    match = _QUANTITY_TEXT_RE.search(quantity_text)
    if match is None:
        return None
    value = float(match.group(1))
    if value <= 0:
        return None
    return _grams_from_measure(match.group(2).lower(), value)


def scale_facts(facts: NutritionFacts, grams: float) -> ScaledNutrition:
    """Scale canonical per-100g ``facts`` to ``grams``; round to 0.1.

    Pure and total: callers resolve ``grams`` first via :func:`resolve_grams`. The
    factor is ``grams / 100`` because the facts are per 100 grams.
    """

    factor = grams / 100.0
    return ScaledNutrition(
        grams=round(grams, 3),
        calories=round(facts.calories * factor, 1),
        protein_g=round(facts.protein_g * factor, 1),
        carbs_g=round(facts.carbs_g * factor, 1),
        fat_g=round(facts.fat_g * factor, 1),
    )


def serving_size_grams(amount: float, unit: str) -> float | None:
    """Resolve a label's printed serving size (``amount`` + ``unit``) to grams.

    Reuses the same mass/volume rule as :func:`resolve_grams` (1 ml ≈ 1 g), but
    deliberately rejects a *count* serving size ("1 bar", "2 cookies") with no
    mass/volume: a confident nutrition-label resolution needs a gram/millilitre
    serving size to convert the printed per-serving facts to canonical per-100g
    (:func:`per_serving_to_per_100g`). Returns ``None`` when ``amount`` is not
    positive or the unit is not a recognised mass/volume, so the caller fails
    closed (routes to ``needs_clarification``) rather than guess.
    """

    if amount <= 0:
        return None
    return _grams_from_measure(_normalize_unit(unit), amount)


def per_serving_to_per_100g(per_serving: NutritionFacts, serving_g: float) -> NutritionFacts:
    """Convert printed **per-serving** label facts to canonical **per-100g** facts.

    Deterministic and pure: each value is scaled by ``100 / serving_g`` so the
    result is the per-100-gram facts the rest of the serving math
    (:func:`scale_facts`) consumes, identical to how a generic-source or OFF
    per-serving fact would be canonicalised. ``serving_g`` must be positive
    (resolved first via :func:`serving_size_grams`).
    """

    factor = 100.0 / serving_g
    return NutritionFacts(
        calories=per_serving.calories * factor,
        protein_g=per_serving.protein_g * factor,
        carbs_g=per_serving.carbs_g * factor,
        fat_g=per_serving.fat_g * factor,
    )


def nutrition_facts_plausible(facts: NutritionFacts) -> bool:
    """Return ``True`` if per-100g ``facts`` are within physical bounds.

    A fact sheet that fails this gate is not an offerable match — it maps to a
    clean ``None`` (non-match) so resolution falls through rather than committing
    an impossible calorie total. Rules:

    - ``calories < 0``: physically impossible (negative energy is the shape of a
      corrupt/garbage nutrient row). Exactly zero is **valid** — genuine
      zero-calorie foods (water, black coffee, diet sodas, zero-cal sweeteners)
      exist in FDC/OFF with ``energy = 0`` and must stay costable; a missing
      energy value is already filtered upstream (FDC drops a food with no kcal
      nutrient; OFF only builds facts when an energy basis is present), so a
      zero reaching this gate is a reported zero, not an absent one.
    - ``calories > 900``: above the physical maximum energy density of food
      (pure fat ≈ 9 kcal/g; pure cooking oils sit at ~884 kcal/100g). A kJ value
      mislabelled as kcal lands ~4× higher and is caught by this ceiling.
    - Any negative macro (``protein_g``, ``carbs_g``, ``fat_g`` ``< 0``): physically
      impossible. Zero macros are explicitly valid (a pure-fat food has zero
      protein and zero carbs).
    - Any non-finite value (``NaN`` or ``±Infinity``) in calories or a macro: not a
      real measurement. ``Infinity`` is already above the ceiling, but ``NaN`` slips
      every comparison (``NaN <= 0``, ``NaN > 900`` and ``NaN < 0`` are all
      ``False``), so it is rejected explicitly. Untrusted fetched JSON can carry
      bare ``NaN``/``Infinity`` tokens (stdlib ``json.loads`` accepts them and
      pydantic floats allow them by default), so this gate must reject them.

    The gate lives in the canonical per-100g space so the same threshold governs
    every source uniformly, including OFF per-serving values converted to per-100g.
    """

    if not all(
        math.isfinite(value)
        for value in (facts.calories, facts.protein_g, facts.carbs_g, facts.fat_g)
    ):
        return False
    if facts.calories < 0 or facts.calories > _MAX_ENERGY_KCAL_PER_100G:
        return False
    if facts.protein_g < 0 or facts.carbs_g < 0 or facts.fat_g < 0:
        return False
    return True
