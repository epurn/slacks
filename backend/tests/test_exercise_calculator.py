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
    CADENCE_STEPS_PER_MINUTE,
    GAME_DURATION_MINUTES,
    MAX_DURATION_MINUTES,
    PACE_KM_PER_HOUR,
    InvalidDurationError,
    MissingBodyWeightError,
    UnknownActivityError,
    has_exercise_detail,
    net_active_calories,
    parse_duration_minutes,
    resolve_duration,
    resolve_exercise,
)
from app.estimator.met_table import lookup_met

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


# --- Distance / steps / games → duration conversions (FTY-167) ----------------


def test_running_distance_converts_to_duration_via_pace() -> None:
    # "ran 5 km": running MET 7.0, 10 km/h pace → 30 min; (7-1)*70*0.5 = 210.0.
    entry = lookup_met("running")
    assert entry is not None
    minutes, assumptions = resolve_duration(entry, "km", 5.0, "5 km")
    assert minutes == pytest.approx(30.0)
    assert assumptions == ("distance→duration: 5 km ÷ 10 km/h = 30 min (running)",)

    burn = resolve_exercise(
        activity="running", weight_kg=70.0, unit="km", amount=5.0, quantity_text="5 km"
    )
    assert burn.met == 7.0
    assert burn.duration_minutes == pytest.approx(30.0)
    assert burn.active_calories == 210.0
    assert burn.assumptions == ("distance→duration: 5 km ÷ 10 km/h = 30 min (running)",)


def test_swimming_a_mile_converts_via_pace() -> None:
    # "swam a mile": no number/unit, a bare mile → 1.609 km ÷ 2.5 km/h ≈ 38.6 min.
    burn = resolve_exercise(
        activity="swimming", weight_kg=70.0, unit=None, amount=None, quantity_text="a mile"
    )
    assert burn.met == 6.0
    assert burn.duration_minutes == pytest.approx(38.62, abs=0.1)
    # (6 - 1) * 70 * (38.62/60) ≈ 225.3 kcal.
    assert burn.active_calories == pytest.approx(225.3, abs=0.2)
    assert burn.assumptions and "distance→duration" in burn.assumptions[0]


def test_step_count_converts_to_walking_duration_via_cadence() -> None:
    # "walked 13000 steps": 13000 ÷ 100 steps/min = 130 min walking.
    burn = resolve_exercise(
        activity="walking",
        weight_kg=70.0,
        unit="steps",
        amount=13000.0,
        quantity_text="13000 steps",
    )
    assert burn.met == 3.5
    assert burn.duration_minutes == pytest.approx(130.0)
    # (3.5 - 1) * 70 * (130/60) ≈ 379.2 kcal.
    assert burn.active_calories == pytest.approx(379.2, abs=0.1)
    assert burn.assumptions == ("steps→duration: 13000 steps ÷ 100 steps/min = 130 min (walking)",)


def test_step_count_without_documented_cadence_cannot_be_costed() -> None:
    # Steps convert via the documented *walking* cadence only. Costing a 13000-step
    # run at 100 steps/min while keeping the running MET would systematically
    # overestimate (130 min at MET 7.0 = 910 kcal vs ~80 min of real running), so a
    # non-walking activity fails closed to clarification like the other conversions.
    with pytest.raises(InvalidDurationError):
        resolve_exercise(
            activity="running",
            weight_kg=70.0,
            unit="steps",
            amount=13000.0,
            quantity_text="13000 steps",
        )
    with pytest.raises(InvalidDurationError):
        resolve_exercise(
            activity="swimming",
            weight_kg=70.0,
            unit="steps",
            amount=5000.0,
            quantity_text="5000 steps",
        )


def test_game_count_converts_to_duration_via_per_game_minutes() -> None:
    # "played 3 games of badminton": 3 × 15 min/game = 45 min; badminton MET 5.5.
    burn = resolve_exercise(
        activity="badminton", weight_kg=70.0, unit="games", amount=3.0, quantity_text="3 games"
    )
    assert burn.met == 5.5
    assert burn.duration_minutes == pytest.approx(45.0)
    # (5.5 - 1) * 70 * (45/60) = 236.25 → 236.2/236.3 after rounding.
    assert burn.active_calories == pytest.approx(236.25, abs=0.1)
    assert burn.assumptions == ("games→duration: 3 × 15 min/game = 45 min (badminton)",)


def test_explicit_duration_beats_distance_and_records_no_assumption() -> None:
    # A stated duration wins over a distance in the same phrase, and adds no
    # inference assumption (nothing was inferred).
    entry = lookup_met("running")
    assert entry is not None
    minutes, assumptions = resolve_duration(entry, "min", 25.0, "25 min over 5 km")
    assert minutes == 25.0
    assert assumptions == ()


def test_distance_without_documented_pace_cannot_be_costed() -> None:
    # A distance for an activity with no documented pace (e.g. rowing) yields no
    # duration and routes to clarification rather than guessing.
    with pytest.raises(InvalidDurationError):
        resolve_exercise(
            activity="rowing", weight_kg=70.0, unit="km", amount=5.0, quantity_text="5 km"
        )


def test_game_count_without_documented_duration_cannot_be_costed() -> None:
    # tennis has a MET entry but no documented per-game minutes; a game count alone
    # cannot be converted.
    with pytest.raises(InvalidDurationError):
        resolve_exercise(
            activity="tennis", weight_kg=70.0, unit="games", amount=2.0, quantity_text="2 games"
        )


@pytest.mark.parametrize(
    ("unit", "amount", "quantity_text", "expected"),
    [
        ("min", 30.0, "", True),  # explicit duration
        ("km", 5.0, "5 km", True),  # distance
        ("steps", 13000.0, "13000 steps", True),  # steps
        ("games", 3.0, "3 games", True),  # games
        (None, None, "a mile", True),  # bare distance in text
        (None, None, "went for a run", False),  # no quantifiable signal
        (None, None, "played sports", False),  # genuinely vague
    ],
)
def test_has_exercise_detail(
    unit: str | None, amount: float | None, quantity_text: str, expected: bool
) -> None:
    assert has_exercise_detail(unit, amount, quantity_text) is expected


def test_documented_conversion_constants_are_sane() -> None:
    # Guard the documented tunables so an accidental edit is caught.
    assert CADENCE_STEPS_PER_MINUTE == {"walking": 100.0}
    assert PACE_KM_PER_HOUR == {"walking": 5.0, "running": 10.0, "swimming": 2.5}
    assert GAME_DURATION_MINUTES == {"badminton": 15.0}
