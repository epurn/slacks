"""Row-level override + derived-column rules for a ``daily_targets`` row.

The pure(ish) helpers that read/write the derived and override columns of a
single :class:`DailyTarget` row, with no knowledge of *which* row to act on (that
is resolution's job). Collected here so the override invariants live in one place:

- **Validation rejects, never clamps** — a manual override outside the documented
  safety band raises :class:`OverrideOutOfBand`; the user's explicit number is
  refused honestly (unlike the derived path, which clamps numbers it produced).
- **Carry-forward keeps a manual choice alive** across a date rollover: a new-date
  row inherits the goal's most recent in-force override until reset or goal
  deletion.
- **Derived recompute leaves overrides untouched** — refreshing the derived
  columns never disturbs an in-force override.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.estimator import constants
from app.models.targets import DailyTarget
from app.schemas.targets import TargetOverrideRequest

from .errors import OverrideOutOfBand


def validate_override(target: DailyTarget, request: TargetOverrideRequest) -> None:
    """Reject any provided override that falls outside its documented band.

    The calorie band is the exact safety band the row was derived against (read
    from its assumptions snapshot — floor 1500/1200 kcal by variant, ceiling 4000).
    Each macro band reuses that calorie ceiling and the Atwater factors as a sanity
    bound (FTY-094 documents no separate per-macro clinical band): a non-negative
    whole-gram target whose energy cannot exceed the calorie ceiling. No new
    numbers are introduced. Raises :class:`OverrideOutOfBand` on the first failure
    so nothing is persisted.
    """

    floor = int(target.assumptions["safety_floor_kcal"])
    ceiling = int(target.assumptions["safety_ceiling_kcal"])

    if request.calorie_target_kcal is not None:
        _check_band("calorie_target_kcal", request.calorie_target_kcal, floor, ceiling)
    if request.protein_target_g is not None:
        _check_band(
            "protein_target_g",
            request.protein_target_g,
            0,
            ceiling // constants.KCAL_PER_G_PROTEIN,
        )
    if request.carbs_target_g is not None:
        _check_band(
            "carbs_target_g",
            request.carbs_target_g,
            0,
            ceiling // constants.KCAL_PER_G_CARB,
        )
    if request.fat_target_g is not None:
        _check_band(
            "fat_target_g",
            request.fat_target_g,
            0,
            ceiling // constants.KCAL_PER_G_FAT,
        )


def _check_band(field: str, value: int, low: int, high: int) -> None:
    if value < low or value > high:
        raise OverrideOutOfBand(field, value, low, high)


def has_override(target: DailyTarget) -> bool:
    """True when any override column on ``target`` is still set."""

    return any(
        column is not None
        for column in (
            target.override_calorie_target_kcal,
            target.override_protein_target_g,
            target.override_carbs_target_g,
            target.override_fat_target_g,
        )
    )


def carry_forward_override(session: Session, goal_id: uuid.UUID, record: DailyTarget) -> None:
    """Copy the goal's most recent in-force override onto a new-date target row.

    Keeps a manual choice alive across a date rollover: the override persists until
    reset or goal deletion, independent of which ``for_date`` row materialises.
    """

    previous = session.scalars(
        select(DailyTarget)
        .where(DailyTarget.goal_id == goal_id)
        .order_by(DailyTarget.created_at.desc())
    ).first()
    if previous is None or not has_override(previous):
        return
    record.override_calorie_target_kcal = previous.override_calorie_target_kcal
    record.override_protein_target_g = previous.override_protein_target_g
    record.override_carbs_target_g = previous.override_carbs_target_g
    record.override_fat_target_g = previous.override_fat_target_g
    record.override_set_at = previous.override_set_at
