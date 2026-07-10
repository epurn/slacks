"""Common count/household portion default tests (FTY-254).

The documented USDA-household-weight table in
:mod:`app.estimator.common_portions`: a stated count of an everyday food
resolves to grams with an explicit ``estimated_common_portion:...`` assumption
label, and everything else fails closed to ``None`` so the caller keeps its
existing routing.
"""

from __future__ import annotations

import pytest

from app.estimator.common_portions import CommonPortion, resolve_common_portion_grams


def _resolve(
    name: str,
    unit: str | None = None,
    amount: float | None = None,
    quantity_text: str = "",
) -> CommonPortion | None:
    return resolve_common_portion_grams(
        name=name, unit=unit, amount=amount, quantity_text=quantity_text
    )


def test_one_banana_defaults_to_a_medium_banana() -> None:
    portion = _resolve("banana", amount=1, quantity_text="one")

    assert portion is not None
    assert portion.grams == pytest.approx(118.0)
    assert portion.assumption == "estimated_common_portion:banana medium 118 g"


@pytest.mark.parametrize(
    ("quantity_text", "grams"),
    [("1 small", 101.0), ("1 medium", 118.0), ("1 large", 136.0)],
)
def test_banana_size_cues_pick_the_documented_weight(quantity_text: str, grams: float) -> None:
    portion = _resolve("banana", amount=1, quantity_text=quantity_text)

    assert portion is not None
    assert portion.grams == pytest.approx(grams)


def test_two_large_eggs_resolve_to_one_hundred_grams() -> None:
    portion = _resolve("eggs", unit="eggs", amount=2, quantity_text="2 large")

    assert portion is not None
    assert portion.grams == pytest.approx(100.0)
    assert portion.assumption == "estimated_common_portion:egg large 50 g"


def test_egg_count_defaults_to_the_us_large_egg() -> None:
    portion = _resolve("eggs", unit=None, amount=3, quantity_text="3")

    assert portion is not None
    assert portion.grams == pytest.approx(150.0)


def test_jumbo_egg_cue_is_recognized() -> None:
    portion = _resolve("eggs", unit="egg", amount=1, quantity_text="1 jumbo")

    assert portion is not None
    assert portion.grams == pytest.approx(63.0)


def test_size_cue_in_the_name_is_recognized() -> None:
    portion = _resolve("large eggs", unit=None, amount=2, quantity_text="two")

    assert portion is not None
    assert portion.grams == pytest.approx(100.0)


def test_a_slice_of_toast_uses_the_toast_slice_weight() -> None:
    portion = _resolve("wheat toast", unit="slice", amount=1, quantity_text="1 slice")

    assert portion is not None
    assert portion.grams == pytest.approx(25.0)
    assert portion.assumption == "estimated_common_portion:toast slice 25 g"


def test_bread_slices_use_the_bread_slice_weight() -> None:
    portion = _resolve("bread", unit="slices", amount=2, quantity_text="2 slices")

    assert portion is not None
    assert portion.grams == pytest.approx(60.0)


def test_a_pat_of_butter() -> None:
    portion = _resolve("butter", unit="pat", amount=1, quantity_text="a pat")

    assert portion is not None
    assert portion.grams == pytest.approx(5.0)
    assert portion.assumption == "estimated_common_portion:butter pat 5 g"


def test_amountless_candidates_fail_closed() -> None:
    assert _resolve("banana") is None


@pytest.mark.parametrize("amount", [0.0, -1.0, 51.0, float("nan"), float("inf")])
def test_out_of_bounds_counts_fail_closed(amount: float) -> None:
    assert _resolve("banana", amount=amount, quantity_text="") is None


def test_composite_dishes_do_not_match_the_component_food() -> None:
    # The head noun is the identity: egg salad is a salad, not a counted egg.
    assert _resolve("egg salad", amount=1, quantity_text="1") is None


def test_unknown_foods_fail_closed() -> None:
    assert _resolve("curry", amount=1, quantity_text="a bowl") is None


def test_measured_units_are_not_treated_as_counts() -> None:
    assert _resolve("banana", unit="cup", amount=1, quantity_text="1 cup") is None
