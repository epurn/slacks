"""Tests for the consolidated active-target query resolver (FTY-120).

Tests cover the shared query predicate used by both targets (raise policy) and
daily_summary (None-returning, read-model-projecting policy) to ensure the
consolidation is behavior-preserving across both call sites.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import MetabolicFormula
from app.models.identity import User, UserProfile
from app.models.targets import Goal
from app.services.targets import (
    TargetNotFound,
    _resolve_active_target,
    compute_daily_target,
    resolve_active_target_row,
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


def _make_active_goal(session: Session, user: User) -> Goal:
    goal = Goal(
        user_id=user.id,
        start_weight_kg=80.0,
        start_date=date(2026, 1, 1),
        target_weight_kg=75.0,
        target_date=date(2026, 4, 1),
        is_active=True,
    )
    session.add(goal)
    session.commit()
    return goal


def _make_inactive_goal(session: Session, user: User) -> Goal:
    goal = Goal(
        user_id=user.id,
        start_weight_kg=80.0,
        start_date=date(2026, 1, 1),
        target_weight_kg=75.0,
        target_date=date(2026, 4, 1),
        is_active=False,
    )
    session.add(goal)
    session.commit()
    return goal


class TestResolveActiveTargetRow:
    """Test the shared active-target query resolver."""

    def test_returns_row_when_active_goal_has_target(self, session: Session) -> None:
        """The query returns the DailyTarget row when the active goal has one for the day."""
        user = _make_user_with_profile(session)
        goal = _make_active_goal(session, user)
        target_day = date(2026, 2, 1)

        target = compute_daily_target(session, user.id, goal.id, user, for_date=target_day)

        # Query should find it.
        result = resolve_active_target_row(session, user.id, target_day)
        assert result is not None
        assert result.id == target.id
        assert result.goal_id == goal.id
        assert result.for_date == target_day

    def test_returns_none_when_no_active_goal(self, session: Session) -> None:
        """The query returns None when the user has no active goal."""
        user = _make_user_with_profile(session)
        # User has no goal at all, so no active goal.

        result = resolve_active_target_row(session, user.id, date(2026, 2, 1))
        assert result is None

    def test_returns_none_when_goal_is_inactive(self, session: Session) -> None:
        """The query returns None when the user's goal is not active."""
        user = _make_user_with_profile(session)
        goal = _make_inactive_goal(session, user)
        target_day = date(2026, 2, 1)

        compute_daily_target(session, user.id, goal.id, user, for_date=target_day)

        # Goal is inactive, so query should not find the row.
        result = resolve_active_target_row(session, user.id, target_day)
        assert result is None

    def test_returns_none_when_no_row_for_day(self, session: Session) -> None:
        """The query returns None when no row exists for the requested day."""
        user = _make_user_with_profile(session)
        goal = _make_active_goal(session, user)

        # Compute a target for one day.
        compute_daily_target(session, user.id, goal.id, user, for_date=date(2026, 2, 1))

        # Query for a different day—no row exists.
        result = resolve_active_target_row(session, user.id, date(2026, 3, 1))
        assert result is None

    def test_returns_none_when_querying_another_user(self, session: Session) -> None:
        """The query is scoped to owner_id and returns None for another user's goal."""
        owner = _make_user_with_profile(session)
        owner_goal = _make_active_goal(session, owner)
        target_day = date(2026, 2, 1)

        compute_daily_target(session, owner.id, owner_goal.id, owner, for_date=target_day)

        other = _make_user_with_profile(session)

        # Other user queries for owner's data—should get None, not cross-user leakage.
        result = resolve_active_target_row(session, other.id, target_day)
        assert result is None


class TestResolveActiveTarget:
    """Test the targets service's active-target resolver (raise policy)."""

    def test_returns_row_when_target_exists(self, session: Session) -> None:
        """_resolve_active_target returns the raw DailyTarget when it exists."""
        user = _make_user_with_profile(session)
        goal = _make_active_goal(session, user)
        target_day = date(2026, 2, 1)

        target = compute_daily_target(session, user.id, goal.id, user, for_date=target_day)

        result = _resolve_active_target(session, user.id, target_day)
        assert result.id == target.id

    def test_raises_target_not_found_when_no_row(self, session: Session) -> None:
        """_resolve_active_target raises TargetNotFound when the row doesn't exist."""
        user = _make_user_with_profile(session)
        _make_active_goal(session, user)

        with pytest.raises(TargetNotFound, match="no active target"):
            _resolve_active_target(session, user.id, date(2026, 3, 1))

    def test_raises_target_not_found_when_no_active_goal(self, session: Session) -> None:
        """_resolve_active_target raises TargetNotFound when no active goal exists."""
        user = _make_user_with_profile(session)

        with pytest.raises(TargetNotFound, match="no active target"):
            _resolve_active_target(session, user.id, date(2026, 2, 1))

    def test_raises_target_not_found_when_goal_inactive(self, session: Session) -> None:
        """_resolve_active_target raises TargetNotFound when the goal is not active."""
        user = _make_user_with_profile(session)
        goal = _make_inactive_goal(session, user)
        target_day = date(2026, 2, 1)

        compute_daily_target(session, user.id, goal.id, user, for_date=target_day)

        with pytest.raises(TargetNotFound, match="no active target"):
            _resolve_active_target(session, user.id, target_day)
