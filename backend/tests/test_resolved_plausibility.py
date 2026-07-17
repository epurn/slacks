"""Resolved-value plausibility gate tests (FTY-368).

Network-free unit fixtures for :mod:`app.estimator.resolved_plausibility`: the
composed-dish detection, the stated-component grams floor, and the resolved-total
gate that catches the 2026-07-16 65-kcal tuna-salad-sandwich incident class while
staying a strict no-op for plausible totals and non-dish items.
"""

from __future__ import annotations

import pytest

from app.estimator.resolved_plausibility import (
    DISH_CLASS_MAX_KCAL_PER_COUNT,
    DISH_CLASS_MIN_KCAL_PER_COUNT,
    ResolvedTotalCheck,
    check_resolved_food_total,
    is_composed_dish,
    refit_assumption,
    stated_component_floor_grams,
)


def _check(
    name: str,
    *,
    unit: str | None = None,
    amount: float | None = None,
    quantity_text: str = "",
    grams: float | None = None,
    calories: float,
) -> ResolvedTotalCheck:
    return check_resolved_food_total(
        name=name,
        unit=unit,
        amount=amount,
        quantity_text=quantity_text,
        grams=grams,
        calories=calories,
    )


# --------------------------------------------------------------------------- #
# Composed-dish detection
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "name",
    [
        "tuna salad sandwich on white bread",
        "chicken wrap",
        "bean burritos",
        "double cheeseburger",
        "breakfast tacos",
    ],
)
def test_composed_dish_names_are_detected(name: str) -> None:
    assert is_composed_dish(name)


@pytest.mark.parametrize(
    "name",
    [
        "egg salad",
        "banana",
        "tuna salad",
        "white bread",
        # Snack-form idioms are counted snacks, never composed meals (FTY-292 class).
        "Toppables peanut butter cracker sandwiches",
        "ice cream sandwich cookies",
    ],
)
def test_non_dish_and_snack_form_names_are_not_detected(name: str) -> None:
    assert not is_composed_dish(name)


def test_dish_word_in_the_unit_counts_as_a_dish() -> None:
    assert is_composed_dish("tuna salad", unit="sandwiches")


def test_snack_form_word_in_the_unit_opts_out() -> None:
    assert not is_composed_dish("toppables", unit="cracker sandwiches")


# --------------------------------------------------------------------------- #
# Stated-component grams floor
# --------------------------------------------------------------------------- #


def test_half_a_can_of_tuna_floors_at_half_the_smallest_retail_can() -> None:
    assert stated_component_floor_grams("about 1/2 a can of tuna") == pytest.approx(42.5)


def test_household_volume_components_convert_through_the_serving_tables() -> None:
    assert stated_component_floor_grams("2 tbsp peanut butter") == pytest.approx(30.0)


def test_mass_components_convert_directly() -> None:
    assert stated_component_floor_grams("with 150g chicken") == pytest.approx(150.0)


def test_largest_stated_component_is_the_binding_floor() -> None:
    floor = stated_component_floor_grams("1 tbsp mayo and 1/2 a can of tuna")
    assert floor == pytest.approx(42.5)


@pytest.mark.parametrize("text", ["", "1 sandwich", "a big one", "1/0 can of tuna"])
def test_unconvertible_or_degenerate_phrases_have_no_floor(text: str) -> None:
    assert stated_component_floor_grams(text) is None


# --------------------------------------------------------------------------- #
# Resolved-total gate
# --------------------------------------------------------------------------- #


def test_the_65_kcal_sandwich_incident_trips_the_class_band() -> None:
    verdict = _check(
        "tuna salad sandwich on white bread",
        unit="sandwich",
        amount=1,
        quantity_text="about 1/2 a can of tuna",
        grams=30.0,
        calories=65.4,
    )
    assert not verdict.plausible
    assert verdict.reason == "dish_total_below_class_band"


def test_a_plausible_sandwich_total_is_a_no_op() -> None:
    verdict = _check(
        "tuna salad sandwich on white bread",
        unit="sandwich",
        amount=1,
        quantity_text="about 1/2 a can of tuna",
        grams=180.0,
        calories=320.0,
    )
    assert verdict == ResolvedTotalCheck(plausible=True)


def test_an_absurdly_high_single_dish_total_trips_the_upper_band() -> None:
    verdict = _check("burrito", amount=1, grams=900.0, calories=4000.0)
    assert not verdict.plausible
    assert verdict.reason == "dish_total_above_class_band"


def test_the_class_band_scales_by_the_counted_dish_amount() -> None:
    low = _check("street tacos", unit="tacos", amount=3, grams=90.0, calories=250.0)
    assert not low.plausible
    assert low.reason == "dish_total_below_class_band"
    # Three large-but-real burritos exceed the single-dish ceiling without tripping.
    high = _check("burritos", unit="burritos", amount=3, grams=900.0, calories=4200.0)
    assert high.plausible


def test_half_a_sandwich_halves_the_floor() -> None:
    verdict = _check("ham sandwich", unit="sandwich", amount=0.5, grams=70.0, calories=80.0)
    assert verdict.plausible


def test_a_resolved_total_beneath_the_stated_component_alone_is_rejected() -> None:
    # Passes the calorie band (a dense per-100g row) but weighs less than the
    # stated half-can of tuna could on its own.
    verdict = _check(
        "tuna salad sandwich on white bread",
        unit="sandwich",
        amount=1,
        quantity_text="about 1/2 a can of tuna",
        grams=30.0,
        calories=120.0,
    )
    assert not verdict.plausible
    assert verdict.reason == "dish_total_below_stated_component"


def test_component_floor_is_skipped_when_grams_are_unknown() -> None:
    verdict = _check(
        "tuna salad sandwich",
        amount=1,
        quantity_text="about 1/2 a can of tuna",
        grams=None,
        calories=320.0,
    )
    assert verdict.plausible


def test_non_dish_items_are_never_gated() -> None:
    assert _check("black coffee", amount=1, grams=240.0, calories=0.0).plausible
    assert _check("banana", amount=1, grams=118.0, calories=105.0).plausible


def test_snack_form_sandwiches_keep_their_small_totals() -> None:
    verdict = _check(
        "peanut butter cracker sandwiches",
        unit="sandwiches",
        amount=3,
        grams=57.0,
        calories=180.0,
    )
    assert verdict.plausible


def test_non_finite_total_fails_closed_to_refit() -> None:
    verdict = _check("ham sandwich", amount=1, grams=100.0, calories=float("nan"))
    assert not verdict.plausible
    assert verdict.reason == "non_finite_total"


def test_bounds_are_generous_documented_tunables() -> None:
    # The band must stay loose: below the lightest real composed dish and above
    # the largest real single restaurant dish (see the cited constants block).
    assert DISH_CLASS_MIN_KCAL_PER_COUNT <= 100.0
    assert DISH_CLASS_MAX_KCAL_PER_COUNT >= 2500.0


def test_refit_assumption_label_is_content_free() -> None:
    assert (
        refit_assumption("dish_total_below_class_band")
        == "resolved_plausibility_refit:dish_total_below_class_band"
    )
