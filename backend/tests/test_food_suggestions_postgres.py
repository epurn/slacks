"""Postgres-parity guard for contextual food suggestions (FTY-340)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.enums import LogEventStatus
from app.models.derived import DerivedFoodItem
from app.models.identity import User, UserProfile
from app.models.log_events import LogEvent
from app.services.food_suggestions import get_food_suggestions
from tests.conftest import upgrade


def test_food_suggestion_read_model_round_trips_on_postgres(pg_engine: Engine) -> None:
    """The owner-scoped join and timestamptz scoring path work on Postgres too."""

    upgrade(pg_engine, "head")
    factory = create_session_factory(pg_engine)
    now = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
    with factory() as session:
        user = User()
        other = User()
        session.add_all([user, other])
        session.flush()
        session.add_all(
            [
                UserProfile(user_id=user.id, timezone="UTC"),
                UserProfile(user_id=other.id, timezone="UTC"),
            ]
        )
        event = LogEvent(
            user_id=user.id,
            raw_text="oatmeal",
            status=LogEventStatus.COMPLETED,
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(days=1),
        )
        other_event = LogEvent(
            user_id=other.id,
            raw_text="secret",
            status=LogEventStatus.COMPLETED,
            created_at=now - timedelta(days=1),
            updated_at=now - timedelta(days=1),
        )
        session.add_all([event, other_event])
        session.flush()
        session.add_all(
            [
                DerivedFoodItem(
                    log_event_id=event.id,
                    user_id=user.id,
                    name="oatmeal",
                    quantity_text="1 bowl",
                    status="resolved",
                    grams=100.0,
                    calories=100.0,
                    created_at=now - timedelta(days=1),
                    updated_at=now - timedelta(days=1),
                ),
                DerivedFoodItem(
                    log_event_id=other_event.id,
                    user_id=other.id,
                    name="secret",
                    quantity_text="1 bowl",
                    status="resolved",
                    grams=100.0,
                    calories=100.0,
                    created_at=now - timedelta(days=1),
                    updated_at=now - timedelta(days=1),
                ),
            ]
        )
        session.commit()

        items = get_food_suggestions(session, user, now=now, limit=8)

    assert [item.label for item in items] == ["oatmeal"]
