"""Shared timezone and date-window utilities (FTY-120).

This module consolidates the day-window computation logic that was duplicated
across log_events, daily_summary, and targets services. Day bounds are computed
in the user's profile timezone (falling back to UTC), enabling correct
attribution of events and targets to calendar days regardless of the user's
local zone or DST transitions.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import UserProfile


def user_timezone(session: Session, owner_id: uuid.UUID) -> ZoneInfo:
    """Resolve the owner's profile timezone, falling back to UTC.

    Day windows and target lookups are computed in this zone. The profile is
    created at registration with a validated IANA name, so this normally loads;
    the UTC fallback keeps queries robust if a profile is somehow absent.
    """

    tz_name = session.scalars(
        select(UserProfile.timezone).where(UserProfile.user_id == owner_id)
    ).one_or_none()
    return ZoneInfo(tz_name or "UTC")


def day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Return the ``[start, end)`` UTC instants bounding ``day`` in ``tz``.

    The bounds are half-open: ``start`` is inclusive, ``end`` is exclusive.
    On DST transition days the bounds account for the zone's rule changes —
    a spring-forward day is < 24h, a fall-back day is > 24h.
    """

    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = datetime.combine(next_day(day), time.min, tzinfo=tz)
    return start_local.astimezone(ZoneInfo("UTC")), end_local.astimezone(ZoneInfo("UTC"))


def next_day(day: date) -> date:
    """Return the calendar day after ``day``."""

    return date.fromordinal(day.toordinal() + 1)


def current_day(session: Session, owner_id: uuid.UUID) -> date:
    """Return today in the owner's profile timezone, falling back to UTC.

    This is the shared resolver for the "what day is it in the user's calendar"
    concept, used across weight entries, goals, targets, daily summaries, and
    log events. The timezone is resolved once and used to compute the current
    date in that zone.
    """

    tz = user_timezone(session, owner_id)
    return datetime.now(tz).date()
