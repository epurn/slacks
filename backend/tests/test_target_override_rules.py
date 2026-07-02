"""Focused unit tests for the extracted row-level override rules (FTY-202).

``validate_override`` / ``has_override`` were extracted from the target service
into :mod:`app.services.targets.override_rules` during the FTY-202 decomposition.
The end-to-end override tests (``test_target_override.py``) exercise them
indirectly through the DB + HTTP surface; these pin the band arithmetic and the
in-force predicate directly, on an in-memory row, so a future edit to the bounds
cannot silently drift. Behaviour is unchanged — this is added coverage only.

The band is read from the row's ``assumptions`` snapshot (floor/ceiling by
metabolic variant); the macro bounds reuse the calorie ceiling and the Atwater
factors (protein/carbs ÷4, fat ÷9) — no new numbers. Validation **rejects**, never
clamps.
"""

from __future__ import annotations

import pytest

from app.estimator import constants
from app.models.targets import DailyTarget
from app.schemas.targets import TargetOverrideRequest
from app.services.targets import OverrideOutOfBand
from app.services.targets.override_rules import (
    has_override,
    validate_override,
)

# The +5 variant band: floor 1500, ceiling 4000 (see target-calculator.md).
_FLOOR = 1500
_CEILING = 4000
_PROTEIN_MAX = _CEILING // constants.KCAL_PER_G_PROTEIN  # 1000
_CARBS_MAX = _CEILING // constants.KCAL_PER_G_CARB  # 1000
_FAT_MAX = _CEILING // constants.KCAL_PER_G_FAT  # 444


def _target() -> DailyTarget:
    """An in-memory row carrying only the assumptions band the validator reads."""

    return DailyTarget(assumptions={"safety_floor_kcal": _FLOOR, "safety_ceiling_kcal": _CEILING})


# ---------------------------------------------------------------------------
# validate_override — accept in band
# ---------------------------------------------------------------------------


def test_validate_accepts_values_inside_the_band() -> None:
    validate_override(
        _target(),
        TargetOverrideRequest(
            calorie_target_kcal=1800,
            protein_target_g=_PROTEIN_MAX,
            carbs_target_g=0,
            fat_target_g=_FAT_MAX,
        ),
    )


def test_validate_accepts_the_band_boundaries() -> None:
    validate_override(_target(), TargetOverrideRequest(calorie_target_kcal=_FLOOR))
    validate_override(_target(), TargetOverrideRequest(calorie_target_kcal=_CEILING))


def test_validate_ignores_omitted_fields() -> None:
    # Only the provided field is checked; an omitted (None) field is never bounded.
    validate_override(_target(), TargetOverrideRequest(protein_target_g=10))


# ---------------------------------------------------------------------------
# validate_override — reject out of band (reject, do not clamp)
# ---------------------------------------------------------------------------


def test_validate_rejects_calorie_below_floor() -> None:
    with pytest.raises(OverrideOutOfBand) as exc:
        validate_override(_target(), TargetOverrideRequest(calorie_target_kcal=_FLOOR - 1))
    err = exc.value
    assert err.field == "calorie_target_kcal"
    assert err.value == _FLOOR - 1
    assert (err.low, err.high) == (_FLOOR, _CEILING)


def test_validate_rejects_calorie_above_ceiling() -> None:
    with pytest.raises(OverrideOutOfBand) as exc:
        validate_override(_target(), TargetOverrideRequest(calorie_target_kcal=_CEILING + 1))
    assert exc.value.field == "calorie_target_kcal"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("protein_target_g", _PROTEIN_MAX + 1),
        ("carbs_target_g", _CARBS_MAX + 1),
        ("fat_target_g", _FAT_MAX + 1),
    ],
)
def test_validate_rejects_macro_above_its_atwater_bound(field: str, value: int) -> None:
    with pytest.raises(OverrideOutOfBand) as exc:
        validate_override(_target(), TargetOverrideRequest(**{field: value}))
    assert exc.value.field == field
    assert exc.value.value == value


def test_validate_reports_the_first_failing_field() -> None:
    with pytest.raises(OverrideOutOfBand) as exc:
        validate_override(
            _target(),
            TargetOverrideRequest(
                calorie_target_kcal=_CEILING + 1,
                protein_target_g=_PROTEIN_MAX + 1,
            ),
        )
    # Calorie is checked before the macros, so nothing past it is reached.
    assert exc.value.field == "calorie_target_kcal"


# ---------------------------------------------------------------------------
# has_override — the in-force predicate
# ---------------------------------------------------------------------------


def test_has_override_false_when_all_columns_null() -> None:
    assert has_override(DailyTarget()) is False


@pytest.mark.parametrize(
    "column",
    [
        "override_calorie_target_kcal",
        "override_protein_target_g",
        "override_carbs_target_g",
        "override_fat_target_g",
    ],
)
def test_has_override_true_when_any_single_column_set(column: str) -> None:
    assert has_override(DailyTarget(**{column: 1})) is True
