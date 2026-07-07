"""Unit tests for the deterministic generic-food serving math (FTY-044).

Pin the quantity → grams resolution rules and the per-100g → portion scaling, plus
the fail-closed ``None`` for quantities that cannot be resolved confidently. No
database, no network — pure functions only.
"""

from __future__ import annotations

import math

import pytest

from app.estimator.food_serving import (
    NutritionFacts,
    nutrition_facts_plausible,
    resolve_grams,
    scale_facts,
)


@pytest.mark.parametrize(
    ("unit", "amount", "quantity_text", "default_serving_g", "expected"),
    [
        # Explicit mass units resolve directly to grams.
        ("g", 150.0, "150g", None, 150.0),
        ("grams", 200.0, "", None, 200.0),
        ("kg", 1.0, "", None, 1000.0),
        ("mg", 500.0, "", None, 0.5),
        ("oz", 1.0, "", None, 28.35),
        # Volume units use the 1 ml ≈ 1 g assumption.
        ("ml", 250.0, "", None, 250.0),
        ("l", 1.0, "", None, 1000.0),
        # Household / cooking measures (FTY-275) convert at their standard volume.
        ("cup", 1.0 / 3.0, "1/3 cup", None, 80.0),  # 240 ml cup → ~80 g
        ("cup", 1.0, "1 cup", None, 240.0),
        ("cups", 2.0, "2 cups", None, 480.0),
        ("tsp", 1.0, "a tsp", None, 5.0),
        ("teaspoon", 1.0, "", None, 5.0),
        ("tbsp", 2.0, "2 tbsp", None, 30.0),
        ("tablespoons", 2.0, "", None, 30.0),
        ("fl oz", 1.0, "", None, 30.0),  # explicit fluid ounce is volume
        ("floz", 1.0, "", None, 30.0),
        ("pint", 1.0, "", None, 473.0),
        ("quart", 1.0, "", None, 946.0),
        ("gallon", 1.0, "", None, 3785.0),
        # Bare "oz" stays a MASS unit (28.35 g), not a fluid ounce.
        ("oz", 1.0, "", None, 28.35),
        # Household units also resolve from the quantity-text fallback.
        (None, None, "1 cup of rice", None, 240.0),
        (None, None, "2 tbsp olive oil", None, 30.0),
        # Count units multiply by the source default serving size.
        (None, 2.0, "two", 50.0, 100.0),
        ("servings", 1.5, "", 80.0, 120.0),
        ("pieces", 3.0, "", 30.0, 90.0),
        # Serving/portion nouns are counts too (FTY-167): "a slice", "3 cracker
        # sandwiches", "a handful of onion rings" resolve via the default serving.
        ("slice", 1.0, "a slice", 120.0, 120.0),
        ("sandwiches", 3.0, "3 cracker sandwiches", 20.0, 60.0),
        ("handful", 1.0, "one handful", 100.0, 100.0),
        ("rings", 7.5, "handful (5-10)", 8.0, 60.0),
        # No structured amount: fall back to scanning the quantity text.
        (None, None, "150 g of rice", None, 150.0),
        (None, None, "250ml milk", None, 250.0),
    ],
)
def test_resolve_grams_resolvable_cases(
    unit: str | None,
    amount: float | None,
    quantity_text: str,
    default_serving_g: float | None,
    expected: float,
) -> None:
    grams = resolve_grams(
        unit=unit,
        amount=amount,
        quantity_text=quantity_text,
        default_serving_g=default_serving_g,
    )
    assert grams is not None
    assert grams == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize(
    ("unit", "amount", "quantity_text", "default_serving_g"),
    [
        # A count with no known serving size cannot be resolved.
        (None, 2.0, "two", None),
        ("servings", 1.0, "", None),
        # No amount and no parseable measured quantity in the text.
        (None, None, "a bowl", None),
        (None, None, "", 100.0),
        # A recognised unit but a non-positive amount.
        ("g", 0.0, "", None),
        # A serving-noun count still needs a known default serving size to resolve.
        ("handful", 1.0, "one handful", None),
        # A genuinely unknown unit with no fallback measure in the text.
        ("zorblax", 1.0, "one zorblax", 100.0),
        # Bare single-letter "t"/"T" are deliberately excluded (ambiguous); the
        # normalized unit lower-cases "T" to "t", and neither resolves.
        ("t", 1.0, "1 t", None),
        ("T", 1.0, "1 T", None),
    ],
)
def test_resolve_grams_unresolvable_returns_none(
    unit: str | None,
    amount: float | None,
    quantity_text: str,
    default_serving_g: float | None,
) -> None:
    assert (
        resolve_grams(
            unit=unit,
            amount=amount,
            quantity_text=quantity_text,
            default_serving_g=default_serving_g,
        )
        is None
    )


def test_scale_facts_scales_per_100g_to_portion() -> None:
    # White rice (cooked), ~130 kcal / 2.6 g protein / 28 g carbs / 0.2 g fat per 100g.
    facts = NutritionFacts(calories=130.0, protein_g=2.6, carbs_g=28.0, fat_g=0.2)

    scaled = scale_facts(facts, 150.0)

    assert scaled.grams == 150.0
    assert scaled.calories == pytest.approx(195.0)  # 130 * 1.5
    assert scaled.protein_g == pytest.approx(3.9)  # 2.6 * 1.5
    assert scaled.carbs_g == pytest.approx(42.0)  # 28 * 1.5
    assert scaled.fat_g == pytest.approx(0.3)  # 0.2 * 1.5


def test_scale_facts_is_proportional_at_100g() -> None:
    facts = NutritionFacts(calories=89.0, protein_g=1.1, carbs_g=23.0, fat_g=0.3)

    scaled = scale_facts(facts, 100.0)

    assert (scaled.calories, scaled.protein_g, scaled.carbs_g, scaled.fat_g) == (
        89.0,
        1.1,
        23.0,
        0.3,
    )


# ---------------------------------------------------------------------------
# Plausibility gate (FTY-115)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("calories", "protein_g", "carbs_g", "fat_g"),
    [
        (130.0, 2.69, 28.2, 0.28),  # white rice — typical food
        (884.0, 0.0, 0.0, 100.0),  # olive oil — high-fat, zero macros valid
        (900.0, 0.0, 0.0, 100.0),  # exactly at cap — should pass (> 900 rejects)
        (1.0, 0.0, 0.0, 0.0),  # minimal positive energy
        (200.0, 0.0, 0.0, 0.0),  # zero macros explicitly valid
        (0.0, 0.0, 0.0, 0.0),  # genuine zero-calorie food (water/black coffee) — costable
    ],
)
def test_nutrition_facts_plausible_valid(
    calories: float, protein_g: float, carbs_g: float, fat_g: float
) -> None:
    facts = NutritionFacts(calories=calories, protein_g=protein_g, carbs_g=carbs_g, fat_g=fat_g)
    assert nutrition_facts_plausible(facts) is True


@pytest.mark.parametrize(
    ("calories", "protein_g", "carbs_g", "fat_g"),
    [
        (-1.0, 0.0, 0.0, 0.0),  # negative energy
        (900.1, 0.0, 0.0, 100.0),  # just above cap
        (1500.0, 10.0, 20.0, 50.0),  # kJ-mislabelled value
        (200.0, -0.1, 0.0, 0.0),  # negative protein
        (200.0, 0.0, -0.1, 0.0),  # negative carbs
        (200.0, 0.0, 0.0, -0.1),  # negative fat
        (math.nan, 0.0, 0.0, 0.0),  # NaN calories slips every comparison
        (200.0, math.nan, 0.0, 0.0),  # NaN protein
        (200.0, 0.0, math.nan, 0.0),  # NaN carbs
        (200.0, 0.0, 0.0, math.nan),  # NaN fat
        (math.inf, 0.0, 0.0, 0.0),  # +Infinity calories
        (200.0, math.inf, 0.0, 0.0),  # +Infinity macro
    ],
)
def test_nutrition_facts_plausible_invalid(
    calories: float, protein_g: float, carbs_g: float, fat_g: float
) -> None:
    facts = NutritionFacts(calories=calories, protein_g=protein_g, carbs_g=carbs_g, fat_g=fat_g)
    assert nutrition_facts_plausible(facts) is False
