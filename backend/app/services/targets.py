"""Target service: derive and persist daily calorie targets (FTY-022).

Ties the profile (body constants) and a goal (the weight trajectory) to the
deterministic calculator, then persists the result as a user-owned
``daily_targets`` row. Every access path is object-level authorized and fails
closed: a caller may only compute targets for *their own* goal.

The profile supplies height, age (from ``birth_year``), and the metabolic-formula
preference; the goal owns the trajectory weights and dates, so the plan is stable
even as the user's measured weight changes.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import MetabolicFormula
from app.estimator import compute_targets
from app.models.identity import User, UserProfile
from app.models.targets import DailyTarget, Goal
from app.schemas.targets import TargetCalculatorInput, TargetCalculatorResult


class GoalForbidden(Exception):
    """Raised when a caller tries to act on a goal they do not own."""


class IncompleteProfileError(Exception):
    """Raised when the profile is missing a field the calculator requires."""


def derive_age_years(birth_year: int, on_date: date) -> int:
    """Whole-year age on ``on_date``.

    The profile stores only ``birth_year`` (privacy-minimal — no birth month/day),
    so age is a whole-year approximation. Documented assumption, exercised by
    tests.
    """

    return on_date.year - birth_year


def build_calculator_input(
    profile: UserProfile, goal: Goal, *, for_date: date
) -> TargetCalculatorInput:
    """Assemble a validated calculator input from a profile and goal.

    Raises :class:`IncompleteProfileError` if the profile has not captured the
    body metrics the math needs, so an incomplete profile can never silently
    produce a bogus target.
    """

    if profile.height_m is None or profile.birth_year is None:
        raise IncompleteProfileError("profile is missing height or birth year")

    formula = MetabolicFormula(profile.metabolic_formula)
    if formula is MetabolicFormula.MIFFLIN_ST_JEOR:
        # The unspecified family default carries no RMR constant: a profile that
        # has not yet captured a +5/-161 variant cannot produce a target.
        raise IncompleteProfileError("profile has not selected a metabolic formula variant")

    return TargetCalculatorInput(
        metabolic_formula=formula,
        height_m=profile.height_m,
        age_years=derive_age_years(profile.birth_year, for_date),
        start_weight_kg=goal.start_weight_kg,
        target_weight_kg=goal.target_weight_kg,
        start_date=goal.start_date,
        target_date=goal.target_date,
    )


def compute_daily_target(
    session: Session,
    owner_id: uuid.UUID,
    goal_id: uuid.UUID,
    current_user: User,
    *,
    for_date: date,
) -> DailyTarget:
    """Compute and persist a daily target for ``owner_id``'s goal.

    Enforces that ``current_user`` owns the goal (fail closed), computes the
    deterministic target, and stores it as a user-owned ``daily_targets`` row with
    the full inputs/assumptions snapshot.
    """

    _authorize(owner_id, current_user)
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

    record = _to_record(owner_id, goal_id, for_date, payload, result)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def _authorize(owner_id: uuid.UUID, current_user: User) -> None:
    """Fail closed unless ``current_user`` owns ``owner_id``'s data."""

    if owner_id != current_user.id:
        raise GoalForbidden("cross-user goal access denied")


def _to_record(
    owner_id: uuid.UUID,
    goal_id: uuid.UUID,
    for_date: date,
    payload: TargetCalculatorInput,
    result: TargetCalculatorResult,
) -> DailyTarget:
    return DailyTarget(
        user_id=owner_id,
        goal_id=goal_id,
        for_date=for_date,
        rmr_kcal=result.rmr_kcal,
        tdee_kcal=result.tdee_kcal,
        daily_calorie_target_kcal=result.daily_calorie_target_kcal,
        clamped=result.clamped,
        inputs=payload.model_dump(mode="json"),
        assumptions=result.assumptions.model_dump(mode="json"),
    )
