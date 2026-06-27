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

import re
from dataclasses import dataclass
from typing import Final

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
