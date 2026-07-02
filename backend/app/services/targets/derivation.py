"""Derive and persist a daily target row.

Ties the profile (body constants) and a goal (the weight trajectory) to the
deterministic calculator, then upserts the result as a user-owned
``daily_targets`` row (FTY-022/FTY-094).

Recompute discipline (the documented invariant, see ``target-calculator.md``): a
recompute refreshes the **derived** columns in place and leaves any in-force
**override** columns untouched; when it materialises a row for a *new* date it
carries the goal's in-force override forward so the choice does not silently lapse
on a date rollover.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.estimator import compute_targets
from app.models.identity import User, UserProfile
from app.models.targets import DailyTarget, Goal
from app.schemas.targets import TargetCalculatorInput, TargetCalculatorResult

from .access import authorize
from .calculator_input import build_calculator_input
from .errors import GoalForbidden, IncompleteProfileError
from .override_rules import carry_forward_override


def compute_daily_target(
    session: Session,
    owner_id: uuid.UUID,
    goal_id: uuid.UUID,
    current_user: User,
    *,
    for_date: date,
) -> DailyTarget:
    """Compute and persist (or recompute) a daily target for ``owner_id``'s goal.

    Enforces that ``current_user`` owns the goal (fail closed), computes the
    deterministic target, and upserts it as a user-owned ``daily_targets`` row.

    Recompute discipline (FTY-095): if a row already exists for ``(goal, for_date)``
    its **derived** columns are refreshed in place and any in-force **override**
    columns are left untouched. When a row is materialised for a *new* date, the
    goal's most recent in-force override is carried forward onto it so a manual
    choice does not lapse on a date rollover.
    """

    authorize(owner_id, current_user)
    goal = session.get(Goal, goal_id)
    if goal is None or goal.user_id != owner_id:
        # No existence oracle: an unowned or missing goal looks the same.
        raise GoalForbidden("goal not found for this user")

    profile = session.scalars(
        select(UserProfile).where(UserProfile.user_id == owner_id)
    ).one_or_none()
    if profile is None:
        raise IncompleteProfileError("profile not found")

    payload = build_calculator_input(profile, goal, for_date=for_date)
    result = compute_targets(payload)

    record = session.scalars(
        select(DailyTarget).where(
            DailyTarget.goal_id == goal_id,
            DailyTarget.for_date == for_date,
        )
    ).one_or_none()
    if record is None:
        record = DailyTarget(user_id=owner_id, goal_id=goal_id, for_date=for_date)
        carry_forward_override(session, goal_id, record)
        session.add(record)
    _apply_derived(record, payload, result)
    session.commit()
    session.refresh(record)
    return record


def _apply_derived(
    record: DailyTarget,
    payload: TargetCalculatorInput,
    result: TargetCalculatorResult,
) -> None:
    """Write the derived columns from a fresh calculation, leaving overrides alone."""

    record.rmr_kcal = result.rmr_kcal
    record.tdee_kcal = result.tdee_kcal
    record.daily_calorie_target_kcal = result.daily_calorie_target_kcal
    record.clamped = result.clamped
    record.protein_target_g = result.protein_target_g
    record.carbs_target_g = result.carbs_target_g
    record.fat_target_g = result.fat_target_g
    record.macros_clamped = result.macros_clamped
    record.inputs = payload.model_dump(mode="json")
    record.assumptions = result.assumptions.model_dump(mode="json")
