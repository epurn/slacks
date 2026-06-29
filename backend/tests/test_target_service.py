"""Integration tests for the target service (FTY-022).

Exercises the profile+goal → persisted daily target path against the migrated
SQLite schema, including object-level authorization (fail closed) and the
incomplete-profile guard.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import MetabolicFormula
from app.models.identity import User, UserProfile
from app.models.targets import DailyTarget, Goal
from app.services.targets import (
    GoalForbidden,
    IncompleteProfileError,
    TargetNotFound,
    compute_daily_target,
    derive_age_years,
    get_active_target,
)


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    db_session = factory()
    try:
        yield db_session
    finally:
        db_session.close()


def _make_user_with_profile(
    session: Session,
    *,
    height_m: float | None = 1.80,
    birth_year: int | None = 1996,
    formula: MetabolicFormula = MetabolicFormula.MIFFLIN_ST_JEOR_PLUS_5,
) -> User:
    user = User()
    session.add(user)
    session.flush()
    session.add(
        UserProfile(
            user_id=user.id,
            height_m=height_m,
            weight_kg=80.0,
            birth_year=birth_year,
            metabolic_formula=formula,
        )
    )
    session.commit()
    return user


def _make_goal(session: Session, user: User) -> Goal:
    goal = Goal(
        user_id=user.id,
        start_weight_kg=80.0,
        start_date=date(2026, 1, 1),
        target_weight_kg=75.0,
        target_date=date(2026, 4, 1),
    )
    session.add(goal)
    session.commit()
    return goal


def test_derive_age_years_uses_birth_year_only() -> None:
    assert derive_age_years(1996, date(2026, 1, 1)) == 30


def test_compute_persists_owned_daily_target(session: Session) -> None:
    user = _make_user_with_profile(session)
    goal = _make_goal(session, user)

    record = compute_daily_target(session, user.id, goal.id, user, for_date=date(2026, 1, 1))

    # Same closed-form example as the unit tests: 80→75 kg over 90 days → 1678.
    assert record.daily_calorie_target_kcal == 1678
    assert record.rmr_kcal == 1780.0
    assert record.tdee_kcal == 2136.0
    assert record.clamped is False
    # Derived macros are now persisted on the row (FTY-094 derivation, FTY-095
    # persistence) so a reset can restore them without re-running the calculator.
    assert record.protein_target_g == 128
    assert record.fat_target_g == 64
    assert record.carbs_target_g == 148
    assert record.macros_clamped is False
    # A freshly derived target carries no override.
    assert record.override_calorie_target_kcal is None
    assert record.override_set_at is None
    # Object-level ownership keys are persisted.
    assert record.user_id == user.id
    assert record.goal_id == goal.id
    # The snapshot is reproducible: inputs and assumptions are stored.
    assert record.inputs["target_weight_kg"] == 75.0
    assert record.assumptions["baseline_activity_multiplier"] == 1.2

    stored = session.get(DailyTarget, record.id)
    assert stored is not None
    assert stored.user_id == user.id


def test_cross_user_compute_fails_closed(session: Session) -> None:
    owner = _make_user_with_profile(session)
    goal = _make_goal(session, owner)
    attacker = _make_user_with_profile(session)

    # Attacker presents their own identity but targets the owner's goal.
    with pytest.raises(GoalForbidden):
        compute_daily_target(session, owner.id, goal.id, attacker, for_date=date(2026, 1, 1))


def test_goal_owned_by_another_user_is_not_found(session: Session) -> None:
    owner = _make_user_with_profile(session)
    other = _make_user_with_profile(session)
    other_goal = Goal(
        user_id=other.id,
        start_weight_kg=80.0,
        start_date=date(2026, 1, 1),
        target_weight_kg=75.0,
        target_date=date(2026, 4, 1),
    )
    session.add(other_goal)
    session.commit()

    # owner authorizes against their own id, but the goal belongs to `other`.
    with pytest.raises(GoalForbidden):
        compute_daily_target(session, owner.id, other_goal.id, owner, for_date=date(2026, 1, 1))


def test_missing_goal_is_not_found(session: Session) -> None:
    user = _make_user_with_profile(session)
    with pytest.raises(GoalForbidden):
        compute_daily_target(session, user.id, uuid.uuid4(), user, for_date=date(2026, 1, 1))


def test_incomplete_profile_is_rejected(session: Session) -> None:
    user = _make_user_with_profile(session, height_m=None)
    goal = _make_goal(session, user)
    with pytest.raises(IncompleteProfileError):
        compute_daily_target(session, user.id, goal.id, user, for_date=date(2026, 1, 1))


# ---------------------------------------------------------------------------
# Carry-forward reads (FTY-127): a target materialised only on goal-creation day
# must still resolve for every later in-horizon day — otherwise GET /target 404s
# the day after onboarding and the mobile gate re-onboards the returning user
# (FTY-103). The daily target is constant across the horizon, so the most recent
# stored row carries forward.
# ---------------------------------------------------------------------------


def test_get_active_target_carries_forward_to_a_later_in_horizon_day(session: Session) -> None:
    """A row stored on creation day resolves for a later in-horizon day (the
    returning-user case): GET /target no longer 404s the day after onboarding."""

    user = _make_user_with_profile(session)
    goal = _make_goal(session, user)  # horizon 2026-01-01 → 2026-04-01
    created = compute_daily_target(session, user.id, goal.id, user, for_date=date(2026, 1, 1))

    # No row was ever stored for 2026-02-01, but it is inside the horizon.
    carried = get_active_target(session, user.id, user, for_date=date(2026, 2, 1))

    assert carried.id == created.id
    assert carried.daily_calorie_target_kcal == created.daily_calorie_target_kcal


def test_get_active_target_before_first_row_is_not_found(session: Session) -> None:
    """A day earlier than the first stored row carries nothing → fail-closed 404."""

    user = _make_user_with_profile(session)
    goal = _make_goal(session, user)
    compute_daily_target(session, user.id, goal.id, user, for_date=date(2026, 2, 1))

    with pytest.raises(TargetNotFound):
        get_active_target(session, user.id, user, for_date=date(2026, 1, 15))


def test_get_active_target_past_horizon_is_not_found(session: Session) -> None:
    """A day past the goal's target_date is not carried — the trajectory is done,
    so the user is steered to a new goal rather than shown a stale deficit (404)."""

    user = _make_user_with_profile(session)
    goal = _make_goal(session, user)  # target_date 2026-04-01
    compute_daily_target(session, user.id, goal.id, user, for_date=date(2026, 1, 1))

    with pytest.raises(TargetNotFound):
        get_active_target(session, user.id, user, for_date=date(2026, 4, 2))


def test_get_active_target_no_goal_is_not_found(session: Session) -> None:
    """No active goal → fail-closed 404 (indistinguishable from cross-user)."""

    user = _make_user_with_profile(session)  # no goal/target seeded
    with pytest.raises(TargetNotFound):
        get_active_target(session, user.id, user, for_date=date(2026, 2, 1))
