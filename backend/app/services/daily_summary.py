"""Daily-summary service: aggregate intake, target, and exercise for a day (FTY-071).

This module owns three contracts:

1. **Object-level authorization.** Every access path runs through
   :func:`_authorize`, which fails closed: a caller may only read their own
   daily summary. A mismatch raises :class:`DailySummaryForbidden`, which the
   router renders as ``404`` so the API never confirms another user's data exists.

2. **Finalized-state filtering.** The exact filter predicate, kept explicit so
   the rule is auditable: ``log_events.voided_at IS NULL AND
   <finalized-event predicate> AND derived_items.status == 'resolved' AND
   current_value IS NOT NULL``. The finalized-event predicate keys on **committed
   resolved items**, not solely on the parent event's transient status
   (:func:`_finalized_event_condition`): a ``resolved`` item counts when its event
   is ``completed`` or ``partially_resolved`` **or** is momentarily ``processing``
   as an answer-triggered scoped re-estimate of a previously-partial event
   (FTY-349). That scoped-``processing`` clause requires **both** a committed
   ``resolved`` sibling **and** an open item-scoped clarification question on a
   still-``unresolved`` component, so it cannot match a **first-pass** ``processing``
   event during the worker's two-commit completion window (resolved rows commit just
   before the ``processing → completed`` transition): a first-pass event owns no such
   question, so nothing counts early. Items on ``pending`` / ``failed`` /
   ``needs_clarification`` events and any ``unresolved`` (uncosted) item are likewise
   excluded, so pending/failed/in-flight work never inflates a total; the scoped
   clause keeps a partial event's siblings counted for the whole re-estimate window
   so the day total never dips and reappears (calm-by-default). A **voided** event
   (FTY-321) is excluded outright even though its rows are retained; the same
   ``voided_at IS NULL`` clause gates the ``uncounted_entries`` predicates too.

3. **Day / timezone resolution.** ``day`` is interpreted in the user's profile
   timezone (falling back to UTC). Items are attributed to a day by their owning
   log event's ``created_at`` — the field ``log-events.md`` already indexes and
   resolves by day for the Today timeline.

4. **No-target representation.** The active-goal target is carried forward within
   the goal's horizon (a day inside the horizon reads the most recent stored row,
   since the daily target is constant across the horizon — see
   ``targets.resolve_carried_target_row``). ``target`` is ``None`` (explicit null,
   never a zero — a zero target and no target are distinct) only when the user has
   no active goal, the day predates the goal's first stored row, or the day is past
   the goal's ``target_date``.

5. **Rounding.** Final sums are rounded to 0.1 (one decimal place) in canonical
   units (kcal, grams), matching the FTY-043/FTY-044 serving-math precision.

Totals, macros, target, and burn are sensitive personal data and are never logged.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.derived import (
    ClarificationQuestion,
    DerivedExerciseItem,
    DerivedFoodItem,
)
from app.models.identity import User
from app.models.log_events import LogEvent
from app.models.targets import DailyTarget, Goal
from app.schemas.daily_summary import (
    DailySummaryDTO,
    DailySummaryExerciseDTO,
    DailySummaryIntakeDTO,
)
from app.schemas.targets import TargetReadModel
from app.services.daily_summary_predicates import (
    _exercise_window_conditions,
    _food_window_conditions,
    _needs_clarification_window_conditions,
    _partial_question_window_conditions,
    _proposed_food_window_conditions,
)
from app.services.targets import build_target_read_model, resolve_carried_target_row
from app.timeutils import current_day, day_bounds_utc, next_day, user_timezone

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


class DailySummaryInvalidRange(Exception):
    """Raised when a range's start date is after its end date (ordering error)."""


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
    if day is None:
        day = current_day(session, owner_id)
    tz = user_timezone(session, owner_id)
    start_utc, end_utc = day_bounds_utc(day, tz)

    intake, has_intake = _aggregate_intake(session, owner_id, start_utc, end_utc)
    uncounted_entries = _aggregate_uncounted_entries(session, owner_id, start_utc, end_utc)
    exercise = _aggregate_exercise(session, owner_id, start_utc, end_utc)
    target = _resolve_target(session, owner_id, day)

    return DailySummaryDTO(
        date=day,
        intake=intake,
        has_intake=has_intake,
        uncounted_entries=uncounted_entries,
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
        raise DailySummaryInvalidRange("'from' must be on or before 'to'")
    if (end.toordinal() - start.toordinal()) + 1 > MAX_RANGE_DAYS:
        raise DailySummaryRangeTooLarge(f"range may not exceed {MAX_RANGE_DAYS} days")

    tz = user_timezone(session, owner_id)
    window_start_utc, _ = day_bounds_utc(start, tz)
    _, window_end_utc = day_bounds_utc(end, tz)

    intake_by_day = _aggregate_intake_by_day(
        session, owner_id, window_start_utc, window_end_utc, tz
    )
    uncounted_by_day = _aggregate_uncounted_entries_by_day(
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
                uncounted_entries=uncounted_by_day.get(day, 0),
                target=targets_by_day.get(day),
                exercise=exercise_by_day.get(day, _exercise_dto([])),
            )
        )
        day = next_day(day)
    return summaries


def _authorize(owner_id: uuid.UUID, current_user: User) -> None:
    """Fail closed unless ``current_user`` owns ``owner_id``'s data."""

    if owner_id != current_user.id:
        raise DailySummaryForbidden("cross-user daily-summary access denied")


def _intake_dto(food_items: list[DerivedFoodItem]) -> DailySummaryIntakeDTO:
    """Sum a day's finalized food items into the intake DTO (rounded to 0.1).

    A macro the item leaves **unknown** (``None`` — a calorie-only ``user_text`` item,
    FTY-279/280) is **skipped**, never coalesced to ``0``: an unknown macro contributes
    no grams, so a macro total reflects only the macros actually known that day
    (``daily-summary.md``). Calories are always known for a finalized item (the
    ``calories IS NOT NULL`` finalized filter), so the headline sum is unaffected.
    """

    return DailySummaryIntakeDTO(
        calories=round(_sum_known(item.calories for item in food_items), _ROUND_DECIMALS),
        protein_g=round(_sum_known(item.protein_g for item in food_items), _ROUND_DECIMALS),
        carbs_g=round(_sum_known(item.carbs_g for item in food_items), _ROUND_DECIMALS),
        fat_g=round(_sum_known(item.fat_g for item in food_items), _ROUND_DECIMALS),
    )


def _sum_known(values: Iterable[float | None]) -> float:
    """Sum only the known (non-``None``) values; an unknown value is skipped, not 0."""

    return sum(value for value in values if value is not None)


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


def _aggregate_uncounted_entries(
    session: Session,
    owner_id: uuid.UUID,
    start_utc: datetime,
    end_utc: datetime,
) -> int:
    """Count the day's logged-but-not-yet-counted entries (single-day path).

    The sum of the user's event-level ``needs_clarification`` log events, open
    item-scoped questions on ``partially_resolved`` events, and ``proposed`` food
    items attributed to the window — the units awaiting a user action. Returns
    ``0`` for a day with no such entries. Bounded ``COUNT`` queries; every item in
    ``[start_utc, end_utc)`` belongs to the single requested day so no per-day
    bucketing is needed here.
    """

    needs_clarification_count = (
        session.scalar(
            select(func.count())
            .select_from(LogEvent)
            .where(*_needs_clarification_window_conditions(owner_id, start_utc, end_utc))
        )
        or 0
    )
    partial_question_count = (
        session.scalar(
            select(func.count(func.distinct(ClarificationQuestion.derived_food_item_id)))
            .select_from(ClarificationQuestion)
            .join(LogEvent, ClarificationQuestion.log_event_id == LogEvent.id)
            .where(*_partial_question_window_conditions(owner_id, start_utc, end_utc))
        )
        or 0
    )
    proposed_count = (
        session.scalar(
            select(func.count())
            .select_from(DerivedFoodItem)
            .join(LogEvent, DerivedFoodItem.log_event_id == LogEvent.id)
            .where(*_proposed_food_window_conditions(owner_id, start_utc, end_utc))
        )
        or 0
    )
    return needs_clarification_count + partial_question_count + proposed_count


def _aggregate_uncounted_entries_by_day(
    session: Session,
    owner_id: uuid.UUID,
    start_utc: datetime,
    end_utc: datetime,
    tz: ZoneInfo,
) -> dict[date, int]:
    """Bucket logged-but-not-yet-counted entries across a window into per-day counts.

    Windowed queries (``needs_clarification`` events, open partial questions, and
    ``proposed`` items), bucketed in Python by the owning event's local day — the
    same attribution rule as the single-day path, computed once for the range.
    Days with no uncounted entries are simply absent (the caller renders them
    ``0``).
    """

    counts: dict[date, int] = defaultdict(int)

    needs_clarification_rows = session.execute(
        select(LogEvent.created_at).where(
            *_needs_clarification_window_conditions(owner_id, start_utc, end_utc)
        )
    ).all()
    for (created_at,) in needs_clarification_rows:
        counts[_to_local_date(created_at, tz)] += 1

    # De-duplicate by component id within each local day: a still-unresolved
    # component may own more than one matching question row across re-estimate
    # rounds (a retained answered row plus a fresh open one), but it is one
    # uncounted entry — the same DISTINCT rule the single-day COUNT applies.
    partial_component_rows = session.execute(
        select(ClarificationQuestion.derived_food_item_id, LogEvent.created_at)
        .select_from(ClarificationQuestion)
        .join(LogEvent, ClarificationQuestion.log_event_id == LogEvent.id)
        .where(*_partial_question_window_conditions(owner_id, start_utc, end_utc))
    ).all()
    components_by_day: dict[date, set[uuid.UUID]] = defaultdict(set)
    for component_id, created_at in partial_component_rows:
        components_by_day[_to_local_date(created_at, tz)].add(component_id)
    for day, component_ids in components_by_day.items():
        counts[day] += len(component_ids)

    proposed_rows = session.execute(
        select(LogEvent.created_at)
        .select_from(DerivedFoodItem)
        .join(LogEvent, DerivedFoodItem.log_event_id == LogEvent.id)
        .where(*_proposed_food_window_conditions(owner_id, start_utc, end_utc))
    ).all()
    for (created_at,) in proposed_rows:
        counts[_to_local_date(created_at, tz)] += 1

    return dict(counts)


def _resolve_target(
    session: Session,
    owner_id: uuid.UUID,
    day: date,
) -> TargetReadModel | None:
    """Return the calorie + macro target read-model for ``owner_id`` on ``day``.

    Resolves the user's active-goal target for ``day``, **carried forward** within
    the goal's horizon (the daily target is constant across the horizon but a row is
    only stored on goal-creation day, so any in-horizon day reads the most recent
    stored row — see :func:`resolve_carried_target_row`), and projects it to the
    read-model (effective / derived / ``derived | user`` source per target,
    FTY-095). Returns ``None`` when there is no active goal, the day predates the
    goal's first row, or the day is past the horizon — explicit null, not zero, to
    distinguish the two states.
    """

    target = resolve_carried_target_row(session, owner_id, day)
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

    The active-goal target is **carried forward** within the goal's horizon, so a
    day inside ``[start, end]`` takes the most recent stored row at or before it
    (the daily target is constant across the horizon but a row is only stored on
    goal-creation day). Implemented as one query (every active-goal row with
    ``for_date <= end``, plus the goal's ``target_date`` for the horizon bound) and
    an in-Python forward-fill — no per-day round trips, matching the FTY-123
    performance contract. Days before the goal's first stored row and days past the
    horizon are simply absent (the caller renders them ``None``), preserving the
    no-target-is-not-zero distinction the single-day path makes.
    """

    rows = session.execute(
        select(DailyTarget, Goal.target_date)
        .join(Goal, DailyTarget.goal_id == Goal.id)
        .where(
            DailyTarget.user_id == owner_id,
            Goal.user_id == owner_id,
            Goal.is_active.is_(True),
            DailyTarget.for_date <= end,
        )
        .order_by(DailyTarget.for_date.asc())
    ).all()
    if not rows:
        return {}

    horizon_end = max(target_date for _, target_date in rows)
    targets = [target for target, _ in rows]

    result: dict[date, TargetReadModel] = {}
    carried: TargetReadModel | None = None
    idx = 0
    day = start
    while day <= end:
        # Advance over every stored row at or before this day; the last one carries.
        while idx < len(targets) and targets[idx].for_date <= day:
            carried = build_target_read_model(targets[idx])
            idx += 1
        if carried is not None and day <= horizon_end:
            result[day] = carried
        day = next_day(day)
    return result
