"""Unit tests for timezone and date-window utilities (FTY-120).

Tests cover the shared day-window computation logic and timezone resolution,
including DST transition days to ensure correct UTC bounds are computed even
when the local day is not 24h.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.models.identity import User, UserProfile
from app.timeutils import day_bounds_utc, next_day, user_timezone


def _create_user_with_timezone(db_engine: Engine, tz_name: str | None) -> uuid.UUID:
    """Create a user and set their timezone, returning user_id."""

    factory = create_session_factory(db_engine)
    with factory() as session:
        # Create user
        user = User()
        session.add(user)
        session.flush()
        user_id = user.id

        # Create profile with timezone
        profile = UserProfile(user_id=user_id, timezone=tz_name)
        session.add(profile)
        session.commit()

    return user_id


class TestUserTimezone:
    """Test timezone resolution from the profile."""

    def test_user_timezone_resolves_profile_timezone(self, db_engine: Engine) -> None:
        """When the profile has a timezone, resolve it."""
        user_id = _create_user_with_timezone(db_engine, "America/New_York")

        factory = create_session_factory(db_engine)
        with factory() as session:
            tz = user_timezone(session, user_id)

        assert tz == ZoneInfo("America/New_York")

    def test_user_timezone_falls_back_to_utc_when_profile_missing_timezone(
        self, db_engine: Engine
    ) -> None:
        """When the profile has no timezone (None), fall back to UTC."""
        user_id = _create_user_with_timezone(db_engine, None)

        factory = create_session_factory(db_engine)
        with factory() as session:
            tz = user_timezone(session, user_id)

        assert tz == ZoneInfo("UTC")

    def test_user_timezone_falls_back_to_utc_when_profile_missing(self, db_engine: Engine) -> None:
        """When the profile row doesn't exist, fall back to UTC."""
        # Create a user without a profile (shouldn't happen, but be defensive)
        factory = create_session_factory(db_engine)
        with factory() as session:
            user = User()
            session.add(user)
            session.flush()
            user_id = user.id
            session.commit()

        with factory() as session:
            tz = user_timezone(session, user_id)

        assert tz == ZoneInfo("UTC")


class TestDayBoundsUTC:
    """Test UTC bounds computation for a day in a given timezone."""

    def test_day_bounds_utc_normal_day_eastern(self) -> None:
        """For a normal (non-DST-transition) day in Eastern, bounds span 24h in UTC."""
        tz = ZoneInfo("America/New_York")
        day = date(2024, 1, 15)  # Normal January day, EST (UTC-5)

        start_utc, end_utc = day_bounds_utc(day, tz)

        # Local midnight on Jan 15 EST = 05:00 UTC Jan 15
        # Local midnight on Jan 16 EST = 05:00 UTC Jan 16
        # So UTC span is 24h
        assert start_utc == datetime(2024, 1, 15, 5, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert end_utc == datetime(2024, 1, 16, 5, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert (end_utc - start_utc).total_seconds() == 24 * 3600

    def test_day_bounds_utc_spring_forward_dst_transition(self) -> None:
        """On a spring-forward DST transition, the local day is < 24h in UTC."""
        tz = ZoneInfo("America/New_York")
        # 2024-03-10 is spring-forward: 02:00 EST → 03:00 EDT (UTC-5 → UTC-4)
        day = date(2024, 3, 10)

        start_utc, end_utc = day_bounds_utc(day, tz)

        # Local midnight start of Mar 10 EST = 05:00 UTC Mar 10
        # Local midnight start of Mar 11 EDT = 04:00 UTC Mar 11
        # So UTC span is 23h
        assert start_utc == datetime(2024, 3, 10, 5, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert end_utc == datetime(2024, 3, 11, 4, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert (end_utc - start_utc).total_seconds() == 23 * 3600

    def test_day_bounds_utc_fall_back_dst_transition(self) -> None:
        """On a fall-back DST transition, the local day is > 24h in UTC."""
        tz = ZoneInfo("America/New_York")
        # 2024-11-03 is fall-back: 02:00 EDT → 01:00 EST (UTC-4 → UTC-5)
        day = date(2024, 11, 3)

        start_utc, end_utc = day_bounds_utc(day, tz)

        # Local midnight start of Nov 3 EDT = 04:00 UTC Nov 3
        # Local midnight start of Nov 4 EST = 05:00 UTC Nov 4
        # So UTC span is 25h
        assert start_utc == datetime(2024, 11, 3, 4, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert end_utc == datetime(2024, 11, 4, 5, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert (end_utc - start_utc).total_seconds() == 25 * 3600

    def test_day_bounds_utc_half_open_interval(self) -> None:
        """The interval is [start, end) — start is inclusive, end is exclusive."""
        tz = ZoneInfo("UTC")
        day = date(2024, 6, 15)

        start_utc, end_utc = day_bounds_utc(day, tz)

        # In UTC, bounds are midnight to midnight
        assert start_utc == datetime(2024, 6, 15, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert end_utc == datetime(2024, 6, 16, 0, 0, 0, tzinfo=ZoneInfo("UTC"))

    def test_day_bounds_utc_utc_zone(self) -> None:
        """For UTC zone, bounds are UTC midnight to UTC midnight."""
        tz = ZoneInfo("UTC")
        day = date(2024, 6, 15)

        start_utc, end_utc = day_bounds_utc(day, tz)

        assert start_utc == datetime(2024, 6, 15, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert end_utc == datetime(2024, 6, 16, 0, 0, 0, tzinfo=ZoneInfo("UTC"))
        assert (end_utc - start_utc).total_seconds() == 24 * 3600


class TestNextDay:
    """Test calendar day incrementing."""

    def test_next_day_normal(self) -> None:
        """The next day after a normal day is the next calendar day."""
        day = date(2024, 1, 15)
        next_d = next_day(day)
        assert next_d == date(2024, 1, 16)

    def test_next_day_month_boundary(self) -> None:
        """The next day rolls the month over correctly."""
        day = date(2024, 1, 31)
        next_d = next_day(day)
        assert next_d == date(2024, 2, 1)

    def test_next_day_year_boundary(self) -> None:
        """The next day rolls the year over correctly."""
        day = date(2024, 12, 31)
        next_d = next_day(day)
        assert next_d == date(2025, 1, 1)

    def test_next_day_leap_year(self) -> None:
        """The next day handles leap-year Feb 29 correctly."""
        day = date(2024, 2, 29)  # 2024 is a leap year
        next_d = next_day(day)
        assert next_d == date(2024, 3, 1)
