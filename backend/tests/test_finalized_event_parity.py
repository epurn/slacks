"""FTY-357 SQL↔Python finalized-event parity tests.

The finalized-event counting rule (FTY-349) has two renderings that cannot be a
single callable — a SQL correlated-``EXISTS`` used by the daily-summary aggregate
reads, and an in-memory id-set query used by the log-events item read. FTY-357
single-sources the definition (the status set + the scoped-``processing``
discriminator) in :mod:`app.services.daily_summary_predicates`; these tests pin
that the two renderings select the **same** finalized events over shared
fixtures, so a future third finalized-reading surface cannot silently diverge.

Fixtures (all on one local day, one owner):
- a **completed** event with a committed resolved item → counts;
- a previously-partial event forced to **``processing``** as a scoped re-estimate
  (a committed resolved sibling + an open item-scoped question on a still-
  ``unresolved`` component) → counts;
- an **initial ``processing``** event carrying a committed resolved item but no
  open question (the worker's two-commit completion window) → excluded;
- a **voided** completed event with a committed resolved item → excluded.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import DerivedItemStatus, LogEventStatus
from app.models.derived import ClarificationQuestion, DerivedExerciseItem, DerivedFoodItem
from app.models.identity import User
from app.models.log_events import LogEvent
from app.services import log_events as log_event_service
from app.services.daily_summary_predicates import (
    _exercise_window_conditions,
    _food_window_conditions,
    _scoped_reestimate_processing,
    _scoped_reestimate_processing_ids,
)
from app.timeutils import day_bounds_utc

_DAY = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
_UTC = ZoneInfo("UTC")


def _resolved_food(user_id: uuid.UUID, event_id: uuid.UUID, name: str) -> DerivedFoodItem:
    return DerivedFoodItem(
        log_event_id=event_id,
        user_id=user_id,
        name=name,
        quantity_text="1 serving",
        amount=1.0,
        status=DerivedItemStatus.RESOLVED,
        grams=80.0,
        calories=180.0,
        protein_g=7.0,
        carbs_g=22.0,
        fat_g=8.0,
        calories_estimated=180.0,
        protein_g_estimated=7.0,
        carbs_g_estimated=22.0,
        fat_g_estimated=8.0,
    )


def _seed_fixtures(db_engine: Engine) -> dict[str, uuid.UUID]:
    """Seed the four shared fixtures and return the interesting event ids."""

    factory = create_session_factory(db_engine)
    with factory() as session:
        user = User()
        session.add(user)
        session.flush()
        user_id = user.id

        # 1. completed event with a committed resolved item → counts.
        completed = LogEvent(
            user_id=user_id, raw_text="oatmeal", status=LogEventStatus.COMPLETED, created_at=_DAY
        )
        session.add(completed)
        session.flush()
        session.add(_resolved_food(user_id, completed.id, "oatmeal"))

        # 2. previously-partial event re-estimating (processing) with a committed
        #    resolved sibling + an open question on a still-unresolved component → counts.
        partial = LogEvent(
            user_id=user_id,
            raw_text="pb toast and milk",
            status=LogEventStatus.PROCESSING,
            created_at=_DAY,
        )
        session.add(partial)
        session.flush()
        resolved_sibling = _resolved_food(user_id, partial.id, "pb toast")
        unresolved = DerivedFoodItem(
            log_event_id=partial.id,
            user_id=user_id,
            name="milk",
            quantity_text="",
            status=DerivedItemStatus.UNRESOLVED,
        )
        session.add_all([resolved_sibling, unresolved])
        session.flush()
        session.add(
            ClarificationQuestion(
                log_event_id=partial.id,
                user_id=user_id,
                question_text="How much milk?",
                options=["a splash", "1/2 cup", "1 cup"],
                derived_food_item_id=unresolved.id,
                position=0,
            )
        )

        # 3. first-pass processing event: a committed resolved row (two-commit
        #    window) but NO open item-scoped question → excluded.
        initial = LogEvent(
            user_id=user_id, raw_text="banana", status=LogEventStatus.PROCESSING, created_at=_DAY
        )
        session.add(initial)
        session.flush()
        session.add(_resolved_food(user_id, initial.id, "banana"))

        # 4. voided completed event with a committed resolved item → excluded.
        voided = LogEvent(
            user_id=user_id,
            raw_text="cookie",
            status=LogEventStatus.COMPLETED,
            created_at=_DAY,
            voided_at=datetime(2026, 7, 10, 13, 0, tzinfo=UTC),
        )
        session.add(voided)
        session.flush()
        session.add(_resolved_food(user_id, voided.id, "cookie"))

        session.commit()
        return {
            "user_id": user_id,
            "completed": completed.id,
            "partial_processing": partial.id,
            "initial_processing": initial.id,
            "voided": voided.id,
        }


def _sql_counted_event_ids(
    session: Session, user_id: uuid.UUID, start: datetime, end: datetime
) -> set[uuid.UUID]:
    """Event ids whose items the daily-summary SQL finalized read selects."""

    food_ids = set(
        session.scalars(
            select(DerivedFoodItem.log_event_id)
            .join(LogEvent, DerivedFoodItem.log_event_id == LogEvent.id)
            .where(*_food_window_conditions(user_id, start, end))
        )
    )
    exercise_ids = set(
        session.scalars(
            select(DerivedExerciseItem.log_event_id)
            .join(LogEvent, DerivedExerciseItem.log_event_id == LogEvent.id)
            .where(*_exercise_window_conditions(user_id, start, end))
        )
    )
    return food_ids | exercise_ids


def test_sql_and_python_finalized_reads_select_the_same_events(db_engine: Engine) -> None:
    """The daily-summary SQL read and the log-events item read count the same events."""

    ids = _seed_fixtures(db_engine)
    user_id = ids["user_id"]
    start, end = day_bounds_utc(_DAY.date(), _UTC)

    factory = create_session_factory(db_engine)
    with factory() as session:
        user = session.get(User, user_id)
        assert user is not None

        sql_event_ids = _sql_counted_event_ids(session, user_id, start, end)

        entries = log_event_service.list_entries_for_day(session, user_id, user, _DAY.date())
        python_event_ids = {entry.event.id for entry in entries if entry.items}

    expected = {ids["completed"], ids["partial_processing"]}
    assert sql_event_ids == expected
    assert python_event_ids == expected
    # The two renderings agree — neither the first-pass processing nor the voided
    # event surfaces on either surface.
    assert sql_event_ids == python_event_ids


def test_scoped_processing_discriminator_renderings_agree(db_engine: Engine) -> None:
    """The SQL and Python scoped-``processing`` discriminators pick the same events."""

    ids = _seed_fixtures(db_engine)
    user_id = ids["user_id"]

    factory = create_session_factory(db_engine)
    with factory() as session:
        scoped_sql = set(
            session.scalars(
                select(LogEvent.id).where(
                    LogEvent.user_id == user_id,
                    _scoped_reestimate_processing(),
                )
            )
        )
        scoped_python = _scoped_reestimate_processing_ids(
            session,
            user_id,
            [ids["partial_processing"], ids["initial_processing"]],
        )

    # Only the genuine scoped re-estimate qualifies; the first-pass processing
    # event (committed rows, no open question) does not.
    assert scoped_sql == {ids["partial_processing"]}
    assert scoped_python == {ids["partial_processing"]}
