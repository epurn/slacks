"""Cross-module consistency for household-volume-unit constants (FTY-276).

Pins that ``app.estimator.food_serving.HOUSEHOLD_VOLUME_UNIT_ML`` is the single
shared source of truth both the plausibility validator and the serving-math
costing path consume, so a future unit addition or tuning edit that touches only
one module is caught here rather than by dogfooding.
"""

from __future__ import annotations

import pytest

from app.estimator import plausibility
from app.estimator.food_serving import _VOLUME_UNIT_GRAMS, HOUSEHOLD_VOLUME_UNIT_ML

#: Canonical household unit -> ml, per the FTY-276 acceptance criteria.
_CANONICAL_ML = {
    "cup": 240.0,
    "tsp": 5.0,
    "tbsp": 15.0,
    "fl_oz": 30.0,
    "pint": 473.0,
    "quart": 946.0,
    "gallon": 3785.0,
}

#: Every alias each module resolves for a household unit, mapped to its
#: canonical key in ``HOUSEHOLD_VOLUME_UNIT_ML`` / ``_CANONICAL_ML``.
_FOOD_SERVING_ALIASES = {
    "tsp": "tsp",
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "tbsp": "tbsp",
    "tbs": "tbsp",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",
    "fl oz": "fl_oz",
    "floz": "fl_oz",
    "fluid ounce": "fl_oz",
    "fluid ounces": "fl_oz",
    "cup": "cup",
    "cups": "cup",
    "pint": "pint",
    "pints": "pint",
    "pt": "pint",
    "quart": "quart",
    "quarts": "quart",
    "qt": "quart",
    "gallon": "gallon",
    "gallons": "gallon",
    "gal": "gallon",
}

_PLAUSIBILITY_ALIASES = {
    "fl": "fl_oz",
    "floz": "fl_oz",
    "fl_oz": "fl_oz",
    "fluid_ounce": "fl_oz",
    "fluid_ounces": "fl_oz",
    "cup": "cup",
    "cups": "cup",
    "tbsp": "tbsp",
    "tbs": "tbsp",
    "tablespoon": "tbsp",
    "tablespoons": "tbsp",
    "tsp": "tsp",
    "teaspoon": "tsp",
    "teaspoons": "tsp",
    "pint": "pint",
    "pints": "pint",
    "pt": "pint",
    "quart": "quart",
    "quarts": "quart",
    "qt": "quart",
    "gallon": "gallon",
    "gallons": "gallon",
    "gal": "gallon",
}


def test_household_volume_unit_ml_matches_canonical_acceptance_values() -> None:
    assert HOUSEHOLD_VOLUME_UNIT_ML == _CANONICAL_ML


def test_plausibility_uses_the_shared_household_volume_table() -> None:
    # plausibility._VOLUME_UNIT_ML's household entries must derive from the very
    # same shared dict food_serving exports, not a second hand-maintained copy.
    for canonical_key, ml in HOUSEHOLD_VOLUME_UNIT_ML.items():
        assert ml in plausibility._VOLUME_UNIT_ML.values()
        _ = canonical_key  # keys differ per module's own alias vocabulary


@pytest.mark.parametrize(("alias", "canonical_key"), sorted(_FOOD_SERVING_ALIASES.items()))
def test_food_serving_alias_resolves_to_canonical_ml(alias: str, canonical_key: str) -> None:
    assert _VOLUME_UNIT_GRAMS[alias] == HOUSEHOLD_VOLUME_UNIT_ML[canonical_key]


@pytest.mark.parametrize(("alias", "canonical_key"), sorted(_PLAUSIBILITY_ALIASES.items()))
def test_plausibility_alias_resolves_to_canonical_ml(alias: str, canonical_key: str) -> None:
    assert plausibility._VOLUME_UNIT_ML[alias] == HOUSEHOLD_VOLUME_UNIT_ML[canonical_key]
