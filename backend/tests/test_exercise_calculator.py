"""Unit tests for the deterministic MET exercise-burn calculator (FTY-043).

Covers the required calculator coverage: exact worked examples against published
Compendium MET values and the net ``(MET - 1)`` convention, duration unit handling,
invalid inputs, and boundary values — zero/extreme duration, missing duration, and
missing/implausible body weight. All math is pure and deterministic, so values are
asserted exactly.
"""

from __future__ import annotations

import pytest

from app.estimator.exercise import (
    MAX_DURATION_MINUTES,
    InvalidDurationError,
    MissingBodyWeightError,
    UnknownActivityError,
    net_active_calories,
    parse_duration_minutes,
    resolve_exercise,
)

# --- Net-active formula: exact worked examples --------------------------------


def test_running_worked_example() -> None:
    # running MET 7.0, 70 kg, 30 min (0.5 h): (7.0 - 1) * 70 * 0.5 = 210.0
    assert net_active_calories(7.0, 70.0, 30.0) == 210.0


def test_walking_worked_example() -> None:
    # walking MET 3.5, 80 kg, 60 min (1 h): (3.5 - 1) * 80 * 1.0 = 200.0
    assert net_active_calories(3.5, 80.0, 60.0) == 200.0


def test_cycling_worked_example() -> None:
    # cycling MET 7.5, 60 kg, 45 min (0.75 h): (7.5 - 1) * 60 * 0.75 = 292.5
    assert net_active_calories(7.5, 60.0, 45.0) == 292.5


def test_net_convention_subtracts_resting_met() -> None:
    # The net credit is strictly below the gross MET burn by exactly the resting
    # (1 MET) component, so TDEE's resting energy is not double-counted.
    gross = 7.0 * 70.0 * 0.5
    net = net_active_calories(7.0, 70.0, 30.0)
    assert net < gross
    assert net == pytest.approx(gross - 1.0 * 70.0 * 0.5)


def test_resolve_uses_curated_met_not_a_guess() -> None:
    burn = resolve_exercise(
        activity="run", weight_kg=70.0, unit="min", amount=30.0, quantity_text="30 min"
    )
    assert burn.met_key == "running"
    assert burn.met == 7.0
    assert burn.duration_minutes == 30.0
    assert burn.active_calories == 210.0


# --- Duration unit handling ---------------------------------------------------


@pytest.mark.parametrize(
    ("unit", "amount", "expected"),
    [
        ("min", 30.0, 30.0),
        ("minutes", 30.0, 30.0),
        ("m", 30.0, 30.0),
        ("h", 1.0, 60.0),
        ("hours", 1.5, 90.0),
        ("hr", 2.0, 120.0),
        ("sec", 120.0, 2.0),
        ("seconds", 90.0, 1.5),
    ],
)
def test_structured_duration_unit_conversions(unit: str, amount: float, expected: float) -> None:
    assert parse_duration_minutes(unit, amount, "") == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("30 min", 30.0),
        ("1.5 hours", 90.0),
        ("45m", 45.0),
        ("a 20 minute walk", 20.0),
    ],
)
def test_duration_falls_back_to_quantity_text(text: str, expected: float) -> None:
    # No structured unit/amount: the duration is recovered from the raw phrase.
    assert parse_duration_minutes(None, None, text) == expected


def test_non_time_unit_is_not_trusted_as_duration() -> None:
    # "5 km" is a distance, not a duration; with no time phrase to fall back on the
    # duration is unknown.
    assert parse_duration_minutes("km", 5.0, "5 km") is None


def test_missing_duration_returns_none() -> None:
    assert parse_duration_minutes(None, None, "a quick session") is None


# --- Boundary values and invalid inputs ---------------------------------------


def test_unknown_activity_is_rejected() -> None:
    with pytest.raises(UnknownActivityError):
        resolve_exercise(
            activity="teleporting", weight_kg=70.0, unit="min", amount=30.0, quantity_text=""
        )


def test_missing_duration_is_rejected() -> None:
    with pytest.raises(InvalidDurationError):
        resolve_exercise(
            activity="run", weight_kg=70.0, unit=None, amount=None, quantity_text="a run"
        )


@pytest.mark.parametrize("amount", [0.0, -5.0])
def test_zero_or_negative_duration_is_rejected(amount: float) -> None:
    with pytest.raises(InvalidDurationError):
        resolve_exercise(
            activity="run", weight_kg=70.0, unit="min", amount=amount, quantity_text=""
        )


def test_extreme_duration_is_rejected() -> None:
    # Beyond 24 h is far likelier a parse error than a real session.
    with pytest.raises(InvalidDurationError):
        resolve_exercise(
            activity="run", weight_kg=70.0, unit="min", amount=2000.0, quantity_text=""
        )


def test_maximum_plausible_duration_is_accepted() -> None:
    # Exactly 24 h is the inclusive upper bound.
    burn = resolve_exercise(
        activity="walking",
        weight_kg=80.0,
        unit="min",
        amount=MAX_DURATION_MINUTES,
        quantity_text="",
    )
    assert burn.duration_minutes == MAX_DURATION_MINUTES


@pytest.mark.parametrize("weight", [None, 0.0, -1.0, 1500.0])
def test_missing_or_implausible_weight_is_rejected(weight: float | None) -> None:
    with pytest.raises(MissingBodyWeightError):
        resolve_exercise(
            activity="run", weight_kg=weight, unit="min", amount=30.0, quantity_text=""
        )
