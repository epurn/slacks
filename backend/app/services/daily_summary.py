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
from collections import defaultdict
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import ColumnElement, select
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
)
from app.schemas.targets import TargetReadModel
from app.services.targets import build_target_read_model

#: Rounding precision for summed totals — matches FTY-043/044 serving-math (0.1).
_ROUND_DECIMALS = 1

#: Upper bound on a range read's span (inclusive days). The widest UI range is
#: 6 months (~180 days); one year leaves generous headroom while keeping a single
#: request bounded — an over-wide span fails closed with 422 rather than scanning
#: an unbounded window.
MAX_RANGE_DAYS = 366

_UTC = ZoneInfo("UTC")


class DailySummaryForbidden(Exception):
    """Raised when a caller tries to access another user's daily summary."""


class DailySummaryRangeTooLarge(Exception):
    """Raised when a range read spans more than :data:`MAX_RANGE_DAYS` days."""


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

    intake, has_intake = _aggregate_intake(session, owner_id, start_utc, end_utc)
    exercise = _aggregate_exercise(session, owner_id, start_utc, end_utc)
    target = _resolve_target(session, owner_id, day)

    return DailySummaryDTO(
        date=day,
        intake=intake,
        has_intake=has_intake,
        target=target,
        exercise=exercise,
    )


def get_daily_summaries(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    start: date,
    end: date,
) -> list[DailySummaryDTO]:
    """Return per-day summaries for every day in ``[start, end]`` (oldest-first).

    This is the range read-model: one windowed query each for intake and exercise
    (bucketed to the owner's local day) plus one for targets, rather than N
    per-day round trips — the client renders an adherence series from a single
    request. Every calendar day in the inclusive range is represented, with
    zeroed intake/burn and a ``None`` target for days that have no finalized data,
    so the shape matches the single-day endpoint exactly — including the
    ``has_intake`` flag, which is ``True`` only for days that have a finalized
    food item, so a consumer can tell an unlogged day from a genuine 0-kcal day.

    ``start`` must be on or before ``end`` and the span may not exceed
    :data:`MAX_RANGE_DAYS` days (:class:`DailySummaryRangeTooLarge` otherwise).
    Raises :class:`DailySummaryForbidden` on cross-user access (fail closed).
    """

    _authorize(owner_id, current_user)
    if start > end:
        raise DailySummaryRangeTooLarge("'from' must be on or before 'to'")
    if (end.toordinal() - start.toordinal()) + 1 > MAX_RANGE_DAYS:
        raise DailySummaryRangeTooLarge(f"range may not exceed {MAX_RANGE_DAYS} days")

    tz = _user_timezone(session, owner_id)
    window_start_utc, _ = _day_bounds_utc(start, tz)
    _, window_end_utc = _day_bounds_utc(end, tz)

    intake_by_day = _aggregate_intake_by_day(
        session, owner_id, window_start_utc, window_end_utc, tz
    )
    exercise_by_day = _aggregate_exercise_by_day(
        session, owner_id, window_start_utc, window_end_utc, tz
    )
    targets_by_day = _resolve_targets_by_day(session, owner_id, start, end)

    summaries: list[DailySummaryDTO] = []
    day = start
    while day <= end:
        # A day is present in ``intake_by_day`` only when it bucketed at least one
        # finalized food item, so membership is exactly the ``has_intake`` signal.
        summaries.append(
            DailySummaryDTO(
                date=day,
                intake=intake_by_day.get(day, _intake_dto([])),
                has_intake=day in intake_by_day,
                target=targets_by_day.get(day),
                exercise=exercise_by_day.get(day, _exercise_dto([])),
            )
        )
        day = _next_day(day)
    return summaries


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


# ── Finalized-state predicate (single source of truth) ─────────────────────────
#
# Both the single-day and range read paths build their queries from these helpers
# so the documented finalized filter is defined exactly once. The predicate:
# ``log_events.status == 'completed'`` AND ``derived_*_items.status == 'resolved'``
# AND the costed-value column ``IS NOT NULL``, windowed by the owning log event's
# ``created_at`` over ``[start, end)``. Day attribution is the event's ``created_at``.


def _food_window_conditions(
    owner_id: uuid.UUID, start_utc: datetime, end_utc: datetime
) -> tuple[ColumnElement[bool], ...]:
    """WHERE conditions selecting one user's finalized food items in a window."""

    return (
        DerivedFoodItem.user_id == owner_id,
        LogEvent.user_id == owner_id,
        LogEvent.status == LogEventStatus.COMPLETED,
        DerivedFoodItem.status == DerivedItemStatus.RESOLVED,
        DerivedFoodItem.calories.isnot(None),
        LogEvent.created_at >= start_utc,
        LogEvent.created_at < end_utc,
    )


def _exercise_window_conditions(
    owner_id: uuid.UUID, start_utc: datetime, end_utc: datetime
) -> tuple[ColumnElement[bool], ...]:
    """WHERE conditions selecting one user's finalized exercise items in a window."""

    return (
        DerivedExerciseItem.user_id == owner_id,
        LogEvent.user_id == owner_id,
        LogEvent.status == LogEventStatus.COMPLETED,
        DerivedExerciseItem.status == DerivedItemStatus.RESOLVED,
        DerivedExerciseItem.active_calories.isnot(None),
        LogEvent.created_at >= start_utc,
        LogEvent.created_at < end_utc,
    )


def _intake_dto(food_items: list[DerivedFoodItem]) -> DailySummaryIntakeDTO:
    """Sum a day's finalized food items into the intake DTO (rounded to 0.1)."""

    return DailySummaryIntakeDTO(
        calories=round(sum(item.calories or 0.0 for item in food_items), _ROUND_DECIMALS),
        protein_g=round(sum(item.protein_g or 0.0 for item in food_items), _ROUND_DECIMALS),
        carbs_g=round(sum(item.carbs_g or 0.0 for item in food_items), _ROUND_DECIMALS),
        fat_g=round(sum(item.fat_g or 0.0 for item in food_items), _ROUND_DECIMALS),
    )


def _exercise_dto(exercise_items: list[DerivedExerciseItem]) -> DailySummaryExerciseDTO:
    """Sum a day's finalized exercise items into the exercise DTO (rounded to 0.1)."""

    return DailySummaryExerciseDTO(
        active_calories=round(
            sum(item.active_calories or 0.0 for item in exercise_items), _ROUND_DECIMALS
        )
    )


def _to_local_date(created_at: datetime, tz: ZoneInfo) -> date:
    """Attribute an event timestamp to a calendar day in the owner's timezone.

    ``created_at`` is stored UTC-aware; a naive value (defensive — some backends
    drop the tzinfo) is treated as UTC before conversion, matching the bounds the
    single-day path compares against.
    """

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=_UTC)
    return created_at.astimezone(tz).date()


def _aggregate_intake(
    session: Session,
    owner_id: uuid.UUID,
    start_utc: datetime,
    end_utc: datetime,
) -> tuple[DailySummaryIntakeDTO, bool]:
    """Sum calories and macros from finalized food items on the day.

    Returns the intake DTO and ``has_intake`` — ``True`` when at least one
    finalized food item was found, so a zeroed-but-logged day is distinguishable
    from an unlogged day (both serialize ``intake`` as zero).
    """

    food_items = list(
        session.scalars(
            select(DerivedFoodItem)
            .join(LogEvent, DerivedFoodItem.log_event_id == LogEvent.id)
            .where(*_food_window_conditions(owner_id, start_utc, end_utc))
        )
    )
    return _intake_dto(food_items), len(food_items) > 0


def _aggregate_exercise(
    session: Session,
    owner_id: uuid.UUID,
    start_utc: datetime,
    end_utc: datetime,
) -> DailySummaryExerciseDTO:
    """Sum active calories from finalized exercise items on the day."""

    exercise_items = list(
        session.scalars(
            select(DerivedExerciseItem)
            .join(LogEvent, DerivedExerciseItem.log_event_id == LogEvent.id)
            .where(*_exercise_window_conditions(owner_id, start_utc, end_utc))
        )
    )
    return _exercise_dto(exercise_items)


def _aggregate_intake_by_day(
    session: Session,
    owner_id: uuid.UUID,
    start_utc: datetime,
    end_utc: datetime,
    tz: ZoneInfo,
) -> dict[date, DailySummaryIntakeDTO]:
    """Bucket finalized food items across a window into per-local-day intake DTOs.

    One windowed query, bucketed in Python by the owning event's local day — the
    same attribution rule as the single-day path, computed once for the range.
    """

    rows = session.execute(
        select(DerivedFoodItem, LogEvent.created_at)
        .join(LogEvent, DerivedFoodItem.log_event_id == LogEvent.id)
        .where(*_food_window_conditions(owner_id, start_utc, end_utc))
    ).all()

    buckets: dict[date, list[DerivedFoodItem]] = defaultdict(list)
    for item, created_at in rows:
        buckets[_to_local_date(created_at, tz)].append(item)
    return {day: _intake_dto(items) for day, items in buckets.items()}


def _aggregate_exercise_by_day(
    session: Session,
    owner_id: uuid.UUID,
    start_utc: datetime,
    end_utc: datetime,
    tz: ZoneInfo,
) -> dict[date, DailySummaryExerciseDTO]:
    """Bucket finalized exercise items across a window into per-local-day DTOs."""

    rows = session.execute(
        select(DerivedExerciseItem, LogEvent.created_at)
        .join(LogEvent, DerivedExerciseItem.log_event_id == LogEvent.id)
        .where(*_exercise_window_conditions(owner_id, start_utc, end_utc))
    ).all()

    buckets: dict[date, list[DerivedExerciseItem]] = defaultdict(list)
    for item, created_at in rows:
        buckets[_to_local_date(created_at, tz)].append(item)
    return {day: _exercise_dto(items) for day, items in buckets.items()}


def _resolve_target(
    session: Session,
    owner_id: uuid.UUID,
    day: date,
) -> TargetReadModel | None:
    """Return the calorie + macro target read-model for ``owner_id`` on ``day``.

    Looks up the ``daily_targets`` row for the user's active goal on ``day`` and
    projects it to the read-model (effective / derived / ``derived | user`` source
    per target, FTY-095). Returns ``None`` when no active goal exists or no target
    row has been stored for the requested day — explicit null, not zero, to
    distinguish the two states.
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
    return build_target_read_model(target)


def _resolve_targets_by_day(
    session: Session,
    owner_id: uuid.UUID,
    start: date,
    end: date,
) -> dict[date, TargetReadModel]:
    """Map ``for_date`` → target read-model for the active goal across a range.

    One query for every ``daily_targets`` row in ``[start, end]``; days without a
    stored row are simply absent (the caller renders them as ``None``), preserving
    the no-target-is-not-zero distinction the single-day path makes.
    """

    targets = session.scalars(
        select(DailyTarget)
        .join(Goal, DailyTarget.goal_id == Goal.id)
        .where(
            DailyTarget.user_id == owner_id,
            Goal.user_id == owner_id,
            Goal.is_active.is_(True),
            DailyTarget.for_date >= start,
            DailyTarget.for_date <= end,
        )
    ).all()

    return {target.for_date: build_target_read_model(target) for target in targets}
