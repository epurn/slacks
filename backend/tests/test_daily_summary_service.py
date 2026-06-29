"""Daily-summary service unit tests (FTY-140).

Tests the exception types raised by get_daily_summaries for validation errors:
- DailySummaryInvalidRange for ordering errors (start > end)
- DailySummaryRangeTooLarge for span errors (span exceeds MAX_RANGE_DAYS)

Both are distinct exception types mapping to 422 in the router.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.models.identity import User
from app.services.daily_summary import (
    MAX_RANGE_DAYS,
    DailySummaryInvalidRange,
    DailySummaryRangeTooLarge,
    get_daily_summaries,
)


def test_ordering_error_raises_distinct_exception(db_engine: Engine) -> None:
    """When start > end, get_daily_summaries raises DailySummaryInvalidRange."""

    factory = create_session_factory(db_engine)
    with factory() as session:
        user = User()
        session.add(user)
        session.commit()

        with pytest.raises(DailySummaryInvalidRange) as exc_info:
            get_daily_summaries(
                session,
                user.id,
                user,
                start=date(2026, 6, 10),
                end=date(2026, 6, 1),
            )

        assert "on or before" in str(exc_info.value)


def test_span_error_raises_range_too_large(db_engine: Engine) -> None:
    """When span exceeds MAX_RANGE_DAYS, get_daily_summaries raises DailySummaryRangeTooLarge."""

    factory = create_session_factory(db_engine)
    with factory() as session:
        user = User()
        session.add(user)
        session.commit()

        with pytest.raises(DailySummaryRangeTooLarge) as exc_info:
            get_daily_summaries(
                session,
                user.id,
                user,
                start=date(2025, 1, 1),
                end=date(2026, 6, 15),  # > MAX_RANGE_DAYS
            )

        assert "may not exceed" in str(exc_info.value)
        assert str(MAX_RANGE_DAYS) in str(exc_info.value)


def test_both_exception_types_are_distinct(db_engine: Engine) -> None:
    """DailySummaryInvalidRange and DailySummaryRangeTooLarge are different types."""

    factory = create_session_factory(db_engine)
    with factory() as session:
        user = User()
        session.add(user)
        session.commit()

        # Ordering error
        with pytest.raises(DailySummaryInvalidRange):
            get_daily_summaries(
                session, user.id, user, start=date(2026, 6, 10), end=date(2026, 6, 1)
            )

        # Span error
        with pytest.raises(DailySummaryRangeTooLarge):
            get_daily_summaries(
                session, user.id, user, start=date(2025, 1, 1), end=date(2026, 6, 15)
            )
