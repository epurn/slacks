"""Daily-summary service: aggregate intake, target, and exercise for a day (FTY-071).

This module owns three contracts:

1. **Object-level authorization.** Every access path runs through
   :func:`_authorize`, which fails closed: a caller may only read their own
   daily summary. A mismatch raises :class:`DailySummaryForbidden`, which the
   router renders as ``404`` so the API never confirms another user's data exists.

2. **Finalized-state filtering.** The exact filter predicate, kept explicit so
   the rule is auditable: ``log_events.status == 'completed' AND derived_items.status
   == 'resolved' AND current_value IS NOT NULL``. Items on ``pending`` /
   ``processing`` / ``failed`` / ``needs_clarification`` events and any
   ``unresolved`` (uncosted) item are excluded so pending/failed work never
   inflates a total. Only ``completed`` events carry committed resolved items
   (FTY-043/FTY-044 commit items in the same transaction as the terminal status).

3. **Day / timezone resolution.** ``day`` is interpreted in the user's profile
   timezone (falling back to UTC). Items are attributed to a day by their owning
   log event's ``created_at`` — the field ``log-events.md`` already indexes and
   resolves by day for the Today timeline.

4. **No-target representation.** When the user has no active goal or no stored
   ``daily_targets`` row for the requested day, ``target`` is ``None`` (explicit
   null) rather than a zero — a zero target and no target are distinct.

5. **Rounding.** Final sums are rounded to 0.1 (one decimal place) in canonical
   units (kcal, grams), matching the FTY-043/FTY-044 serving-math precision.

Totals, macros, target, and burn are sensitive personal data and are never logged.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import DerivedItemStatus, LogEventStatus
from app.models.derived import DerivedExerciseItem, DerivedFoodItem
from app.models.identity import User, UserProfile
from app.models.log_events import LogEvent
from app.models.targets import DailyTarget, Goal
from app.schemas.daily_summary import (
    DailySummaryDTO,
    DailySummaryExerciseDTO,
    DailySummaryIntakeDTO,
    DailySummaryTargetDTO,
)

#: Rounding precision for summed totals — matches FTY-043/044 serving-math (0.1).
_ROUND_DECIMALS = 1


class DailySummaryForbidden(Exception):
    """Raised when a caller tries to access another user's daily summary."""


def get_daily_summary(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    day: date | None = None,
) -> DailySummaryDTO:
    """Return the daily summary for ``owner_id`` on ``day`` in their timezone.

    ``day`` defaults to the current day in the user's profile timezone. Raises
    :class:`DailySummaryForbidden` on cross-user access (fail closed).
    """

    _authorize(owner_id, current_user)
    tz = _user_timezone(session, owner_id)
    if day is None:
        day = datetime.now(tz).date()
    start_utc, end_utc = _day_bounds_utc(day, tz)

    intake = _aggregate_intake(session, owner_id, start_utc, end_utc)
    exercise = _aggregate_exercise(session, owner_id, start_utc, end_utc)
    target = _resolve_target(session, owner_id, day)

    return DailySummaryDTO(date=day, intake=intake, target=target, exercise=exercise)


def _authorize(owner_id: uuid.UUID, current_user: User) -> None:
    """Fail closed unless ``current_user`` owns ``owner_id``'s data."""

    if owner_id != current_user.id:
        raise DailySummaryForbidden("cross-user daily-summary access denied")


def _user_timezone(session: Session, owner_id: uuid.UUID) -> ZoneInfo:
    """Resolve the owner's profile timezone, falling back to UTC.

    Day windows are computed in this zone. The UTC fallback keeps the endpoint
    robust if a profile is somehow absent.
    """

    tz_name = session.scalars(
        select(UserProfile.timezone).where(UserProfile.user_id == owner_id)
    ).one_or_none()
    return ZoneInfo(tz_name or "UTC")


def _day_bounds_utc(day: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """Return the ``[start, end)`` UTC instants bounding ``day`` in ``tz``."""

    start_local = datetime.combine(day, time.min, tzinfo=tz)
    end_local = datetime.combine(_next_day(day), time.min, tzinfo=tz)
    return start_local.astimezone(ZoneInfo("UTC")), end_local.astimezone(ZoneInfo("UTC"))


def _next_day(day: date) -> date:
    return date.fromordinal(day.toordinal() + 1)


def _aggregate_intake(
    session: Session,
    owner_id: uuid.UUID,
    start_utc: datetime,
    end_utc: datetime,
) -> DailySummaryIntakeDTO:
    """Sum calories and macros from finalized food items on the day.

    Finalized filter (documented predicate):
    ``log_events.status == 'completed'``
    AND ``derived_food_items.status == 'resolved'``
    AND ``derived_food_items.calories IS NOT NULL``.

    Items on non-``completed`` events and uncosted (``NULL`` calories) items are
    excluded. Day attribution is via the owning log event's ``created_at``.
    """

    food_items = list(
        session.scalars(
            select(DerivedFoodItem)
            .join(LogEvent, DerivedFoodItem.log_event_id == LogEvent.id)
            .where(
                DerivedFoodItem.user_id == owner_id,
                LogEvent.user_id == owner_id,
                LogEvent.status == LogEventStatus.COMPLETED,
                DerivedFoodItem.status == DerivedItemStatus.RESOLVED,
                DerivedFoodItem.calories.isnot(None),
                LogEvent.created_at >= start_utc,
                LogEvent.created_at < end_utc,
            )
        )
    )

    return DailySummaryIntakeDTO(
        calories=round(sum(item.calories or 0.0 for item in food_items), _ROUND_DECIMALS),
        protein_g=round(sum(item.protein_g or 0.0 for item in food_items), _ROUND_DECIMALS),
        carbs_g=round(sum(item.carbs_g or 0.0 for item in food_items), _ROUND_DECIMALS),
        fat_g=round(sum(item.fat_g or 0.0 for item in food_items), _ROUND_DECIMALS),
    )


def _aggregate_exercise(
    session: Session,
    owner_id: uuid.UUID,
    start_utc: datetime,
    end_utc: datetime,
) -> DailySummaryExerciseDTO:
    """Sum active calories from finalized exercise items on the day.

    Finalized filter (documented predicate):
    ``log_events.status == 'completed'``
    AND ``derived_exercise_items.status == 'resolved'``
    AND ``derived_exercise_items.active_calories IS NOT NULL``.

    Day attribution is via the owning log event's ``created_at``.
    """

    exercise_items = list(
        session.scalars(
            select(DerivedExerciseItem)
            .join(LogEvent, DerivedExerciseItem.log_event_id == LogEvent.id)
            .where(
                DerivedExerciseItem.user_id == owner_id,
                LogEvent.user_id == owner_id,
                LogEvent.status == LogEventStatus.COMPLETED,
                DerivedExerciseItem.status == DerivedItemStatus.RESOLVED,
                DerivedExerciseItem.active_calories.isnot(None),
                LogEvent.created_at >= start_utc,
                LogEvent.created_at < end_utc,
            )
        )
    )

    return DailySummaryExerciseDTO(
        active_calories=round(
            sum(item.active_calories or 0.0 for item in exercise_items), _ROUND_DECIMALS
        )
    )


def _resolve_target(
    session: Session,
    owner_id: uuid.UUID,
    day: date,
) -> DailySummaryTargetDTO | None:
    """Return the daily calorie target for ``owner_id`` on ``day``, or ``None``.

    Looks up the ``daily_targets`` row for the user's active goal on ``day``.
    Returns ``None`` when no active goal exists or no target row has been stored
    for the requested day — explicit null, not zero, to distinguish the two states.
    """

    target = session.scalars(
        select(DailyTarget)
        .join(Goal, DailyTarget.goal_id == Goal.id)
        .where(
            DailyTarget.user_id == owner_id,
            Goal.user_id == owner_id,
            Goal.is_active.is_(True),
            DailyTarget.for_date == day,
        )
    ).one_or_none()

    if target is None:
        return None
    return DailySummaryTargetDTO(calories=target.daily_calorie_target_kcal)
