"""Unit tests for the deterministic target calculator (FTY-022).

Covers the required calculator coverage: exact worked examples, unit conversions,
invalid inputs, and boundary values — including implausible goals and the safety
floor/ceiling. All math is pure and deterministic, so values are asserted
exactly.
"""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.enums import GoalDirection, MetabolicFormula
from app.estimator import (
    compute_targets,
    constants,
    resting_metabolic_rate,
    total_daily_energy_expenditure,
)
from app.schemas.targets import TargetCalculatorInput

MALE = MetabolicFormula.MIFFLIN_ST_JEOR_PLUS_5
FEMALE = MetabolicFormula.MIFFLIN_ST_JEOR_MINUS_161


def _input(**overrides: object) -> TargetCalculatorInput:
    """A valid baseline input; override individual fields per test."""

    base: dict[str, object] = {
        "metabolic_formula": MALE,
        "height_m": 1.80,
        "age_years": 30,
        "start_weight_kg": 80.0,
        "target_weight_kg": 80.0,
        "start_date": date(2026, 1, 1),
        "target_date": date(2026, 4, 1),  # 90-day horizon
    }
    base.update(overrides)
    return TargetCalculatorInput(**base)  # type: ignore[arg-type]


# --- RMR / TDEE exact worked examples (both formula variants) ----------------


def test_rmr_male_worked_example() -> None:
    # 10·80 + 6.25·180 − 5·30 + 5 = 1780.0
    assert resting_metabolic_rate(MALE, 80.0, 1.80, 30) == 1780.0


def test_rmr_female_worked_example() -> None:
    # 10·60 + 6.25·170 − 5·30 − 161 = 1351.5
    assert resting_metabolic_rate(FEMALE, 60.0, 1.70, 30) == 1351.5


def test_rmr_variants_differ_by_mifflin_constant() -> None:
    male = resting_metabolic_rate(MALE, 70.0, 1.75, 40)
    female = resting_metabolic_rate(FEMALE, 70.0, 1.75, 40)
    # The only difference between variants is +5 vs -161 → a 166 kcal gap.
    assert round(male - female, 1) == 166.0


def test_tdee_is_rmr_times_baseline_multiplier() -> None:
    assert total_daily_energy_expenditure(1780.0) == 2136.0  # 1780 × 1.2
    assert constants.BASELINE_ACTIVITY_MULTIPLIER == 1.2


# --- Unit conversion ---------------------------------------------------------


def test_height_metres_are_converted_to_centimetres() -> None:
    # Imperial 200 lb / 5'10" / 40yo male, converted to canonical kg/m by the
    # caller (90.718 kg, 1.778 m); the calculator converts m→cm internally.
    assert resting_metabolic_rate(MALE, 90.718, 1.778, 40) == 1823.4


# --- Dynamic goal planning: exact examples -----------------------------------


def test_maintenance_target_equals_tdee() -> None:
    # target == start weight: the dynamic plan reduces to maintenance (TDEE).
    result = compute_targets(_input(target_weight_kg=80.0))
    assert result.direction is GoalDirection.MAINTAIN
    assert result.tdee_kcal == 2136.0
    assert result.daily_calorie_target_kcal == 2136
    assert result.clamped is False


def test_weight_loss_target_is_a_deficit_below_tdee() -> None:
    # Male 80→75 kg over 90 days. Hand-checked closed form ≈ 1677.5 → 1678.
    result = compute_targets(_input(target_weight_kg=75.0))
    assert result.direction is GoalDirection.LOSS
    assert result.daily_calorie_target_kcal == 1678
    assert result.daily_calorie_target_kcal < result.tdee_kcal
    assert result.clamped is False


def test_longer_horizon_is_gentler_than_shorter_horizon() -> None:
    # Same 5 kg loss over a year is a smaller deficit (closer to TDEE) than over
    # 90 days — the dynamic model accounts for falling expenditure.
    short = compute_targets(_input(target_weight_kg=75.0))
    long = compute_targets(
        _input(target_weight_kg=75.0, target_date=date(2027, 1, 1))  # ~365 days
    )
    assert long.daily_calorie_target_kcal == 1998
    assert long.daily_calorie_target_kcal > short.daily_calorie_target_kcal


def test_weight_gain_target_is_a_surplus_above_tdee() -> None:
    result = compute_targets(_input(start_weight_kg=70.0, target_weight_kg=75.0))
    assert result.direction is GoalDirection.GAIN
    assert result.daily_calorie_target_kcal > result.tdee_kcal
    assert result.clamped is False


# --- Safety floor / ceiling (implausible goals) ------------------------------


def test_implausibly_fast_loss_is_clamped_to_floor() -> None:
    # Male 80→60 kg in 30 days demands a negative intake; refused and clamped up
    # to the male floor rather than returned as guidance.
    result = compute_targets(_input(target_weight_kg=60.0, target_date=date(2026, 1, 31)))
    assert result.daily_calorie_target_kcal == constants.SAFETY_FLOOR_KCAL_PLUS5
    assert result.clamped is True


def test_female_floor_is_lower_than_male_floor() -> None:
    common = dict(
        height_m=1.65,
        target_weight_kg=45.0,
        start_weight_kg=70.0,
        target_date=date(2026, 1, 31),
    )
    male = compute_targets(_input(metabolic_formula=MALE, **common))
    female = compute_targets(_input(metabolic_formula=FEMALE, **common))
    assert male.daily_calorie_target_kcal == constants.SAFETY_FLOOR_KCAL_PLUS5
    assert female.daily_calorie_target_kcal == constants.SAFETY_FLOOR_KCAL_MINUS161
    assert female.daily_calorie_target_kcal < male.daily_calorie_target_kcal


def test_implausibly_fast_gain_is_clamped_to_ceiling() -> None:
    result = compute_targets(
        _input(
            metabolic_formula=FEMALE,
            height_m=1.60,
            start_weight_kg=50.0,
            target_weight_kg=80.0,
            target_date=date(2026, 1, 11),
        )
    )
    assert result.daily_calorie_target_kcal == constants.SAFETY_CEILING_KCAL
    assert result.clamped is True


# --- Macro targets (FTY-094) -------------------------------------------------


def test_maintenance_macros_pinned_example() -> None:
    # Male 80 kg, 1.80 m, age 30, target 80 kg → 2136 kcal.
    # protein = round(1.6 × 80)            = 128 g
    # fat     = round(0.30 × 2136 / 9)     = 71 g  (> 0.8 × 80 = 64 g floor)
    # carbs   = round((2136 − 512 − 639)/4) = round(246.25) = 246 g
    result = compute_targets(_input(target_weight_kg=80.0))
    assert result.daily_calorie_target_kcal == 2136
    assert result.protein_target_g == 128
    assert result.fat_target_g == 71
    assert result.carbs_target_g == 246
    assert result.macros_clamped is False
    # The macro kcal reconstruct within one gram's rounding of the calorie target.
    macro_kcal = 4 * result.protein_target_g + 4 * result.carbs_target_g + 9 * result.fat_target_g
    assert abs(macro_kcal - result.daily_calorie_target_kcal) <= 4


def test_weight_loss_macros_fat_floor_pinned_example() -> None:
    # Same profile, target 75 kg over 90 days → 1678 kcal.
    # protein stays anchored to the 80 kg START weight (not the 75 kg goal) = 128 g.
    # fat: 0.8 × 80 = 64 g floor wins over round(0.30 × 1678 / 9) = 56 g.
    result = compute_targets(_input(target_weight_kg=75.0))
    assert result.daily_calorie_target_kcal == 1678
    assert result.direction is GoalDirection.LOSS
    assert result.protein_target_g == 128
    assert result.fat_target_g == 64
    assert result.macros_clamped is False
    # carbs = round((1678 − 512 − 576) / 4) = round(147.5) = 148 g (half up).
    assert result.carbs_target_g == 148


def test_protein_anchors_to_start_weight_not_goal_weight() -> None:
    # Proof of the anchor choice: the lower goal weight must NOT lower protein,
    # and the floor (not the percentage share) must set fat in the deficit.
    maintain = compute_targets(_input(target_weight_kg=80.0))
    loss = compute_targets(_input(target_weight_kg=75.0))
    assert loss.protein_target_g == maintain.protein_target_g == 128
    # Fat in the deficit is the 0.8 g/kg floor, below the maintenance % share.
    assert loss.fat_target_g == 64
    assert loss.fat_target_g < maintain.fat_target_g
    fat_floor_g = round(constants.FAT_FLOOR_G_PER_KG * 80.0)
    fat_share_g = round(constants.FAT_PCT_OF_CALORIES * loss.daily_calorie_target_kcal / 9)
    assert loss.fat_target_g == fat_floor_g > fat_share_g


def test_over_constrained_macros_clamp_carbs_to_zero() -> None:
    # Heavy start weight + a deep deficit clamps the calorie target to the floor;
    # protein + fat then meet/exceed it, so carbohydrate floors at 0 and the flag
    # is honest rather than silently negative.
    result = compute_targets(
        _input(
            metabolic_formula=FEMALE,
            height_m=1.60,
            start_weight_kg=90.0,
            target_weight_kg=60.0,
            target_date=date(2026, 1, 31),  # 30-day horizon → calorie floor
        )
    )
    assert result.daily_calorie_target_kcal == constants.SAFETY_FLOOR_KCAL_MINUS161  # 1200
    assert result.protein_target_g == 144  # round(1.6 × 90)
    assert result.fat_target_g == 72  # round(0.8 × 90) floor, > round(0.30×1200/9)=40
    # 4×144 + 9×72 = 1224 kcal ≥ 1200 → carbs floored at 0, flag set.
    assert result.carbs_target_g == 0
    assert result.macros_clamped is True


def test_macros_are_never_negative() -> None:
    # Even in the over-constrained case the gram outputs stay non-negative.
    result = compute_targets(
        _input(
            metabolic_formula=FEMALE,
            height_m=1.60,
            start_weight_kg=95.0,
            target_weight_kg=60.0,
            target_date=date(2026, 1, 31),
        )
    )
    assert result.carbs_target_g >= 0
    assert result.protein_target_g >= 0
    assert result.fat_target_g >= 0


def test_macro_assumptions_snapshot_documents_defaults() -> None:
    assumptions = compute_targets(_input(target_weight_kg=75.0)).assumptions
    assert assumptions.protein_g_per_kg == 1.6
    assert assumptions.protein_anchor == "start_weight_kg"
    assert assumptions.fat_pct_of_calories == 0.30
    assert assumptions.fat_floor_g_per_kg == 0.8
    assert "half up" in assumptions.macro_rounding


# --- Assumptions snapshot ----------------------------------------------------


def test_result_carries_documented_assumptions() -> None:
    result = compute_targets(_input(target_weight_kg=75.0))
    assumptions = result.assumptions
    assert assumptions.baseline_activity_multiplier == 1.2
    assert assumptions.energy_density_kcal_per_kg == 7700.0
    assert assumptions.rmr_mass_coefficient_kcal_per_kg == 10.0
    assert assumptions.safety_floor_kcal == constants.SAFETY_FLOOR_KCAL_PLUS5
    assert assumptions.safety_ceiling_kcal == constants.SAFETY_CEILING_KCAL
    assert "mifflin" in assumptions.model.lower()


def test_calculator_is_deterministic() -> None:
    payload = _input(target_weight_kg=75.0)
    assert compute_targets(payload) == compute_targets(payload)


# --- Boundary values ---------------------------------------------------------


def test_minimum_one_day_horizon_is_accepted() -> None:
    result = compute_targets(_input(target_weight_kg=79.0, target_date=date(2026, 1, 2)))
    assert result.horizon_days == 1


@pytest.mark.parametrize("age", [13, 120])
def test_age_bounds_are_accepted(age: int) -> None:
    assert compute_targets(_input(age_years=age)).rmr_kcal > 0


# --- Invalid inputs (boundary validation) ------------------------------------


def test_target_date_must_be_after_start_date() -> None:
    with pytest.raises(ValidationError):
        _input(target_date=date(2026, 1, 1))  # equal to start_date
    with pytest.raises(ValidationError):
        _input(target_date=date(2025, 12, 1))  # before start_date


@pytest.mark.parametrize("height", [0.0, -1.0, 3.5])
def test_invalid_height_is_rejected(height: float) -> None:
    with pytest.raises(ValidationError):
        _input(height_m=height)


@pytest.mark.parametrize("age", [12, 121, -1])
def test_out_of_range_age_is_rejected(age: int) -> None:
    with pytest.raises(ValidationError):
        _input(age_years=age)


@pytest.mark.parametrize("weight", [0.0, -5.0, 1500.0])
def test_invalid_weight_is_rejected(weight: float) -> None:
    with pytest.raises(ValidationError):
        _input(start_weight_kg=weight)


def test_unknown_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _input(activity_level="sedentary")
