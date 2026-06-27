"""Unit tests for the deterministic generic-food serving math (FTY-044).

Pin the quantity → grams resolution rules and the per-100g → portion scaling, plus
the fail-closed ``None`` for quantities that cannot be resolved confidently. No
database, no network — pure functions only.
"""

from __future__ import annotations

import pytest

from app.estimator.food_serving import (
    NutritionFacts,
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
        # Count units multiply by the source default serving size.
        (None, 2.0, "two", 50.0, 100.0),
        ("servings", 1.5, "", 80.0, 120.0),
        ("pieces", 3.0, "", 30.0, 90.0),
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
        # An unrecognised unit with no fallback in the text.
        ("handful", 1.0, "one handful", 100.0),
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
