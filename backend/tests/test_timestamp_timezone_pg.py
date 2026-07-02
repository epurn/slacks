"""Postgres-parity guard for timestamp / timezone correctness (FTY-173).

The day-bucketing math and the ``timestamptz`` round-trip are exactly the
SQLite-vs-Postgres class of bug the *Verify at the highest applicable level*
principle guards against: SQLite has no native timezone type and tolerates naive
handling that Postgres does not, so a bucketing or serialization fix proven only
against SQLite has not been proven where production runs.

This module exercises the real behaviour against a live Postgres engine with
**fixed timezone fixtures** — a non-UTC zone (America/New_York) and a half-hour
offset zone (Asia/Kolkata, UTC+5:30) — covering the three things the story
enforces end-to-end:

1. **Storage** — ``created_at`` round-trips through ``timestamptz`` as the same
   UTC instant, tz-aware.
2. **Serialization** — the event DTO serializes ``created_at``/``updated_at`` with
   an explicit UTC offset (never a naive string a client would read as local).
3. **Bucketing** — list-today resolves the day boundary in the user's profile
   timezone, so a previous-local-evening entry lands on the prior local day and a
   half-hour-offset zone buckets by its own local midnight.

It is opt-in: the ``pg_engine`` fixture skips the test when
``FATTY_TEST_DATABASE_URL`` is unset, so a fresh checkout and the SQLite-only
local/CI path stay green without a running Postgres (CI wires the env var against
a real Postgres service, FTY-144).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.models.identity import User, UserProfile
from app.models.log_events import LogEvent
from app.schemas.log_events import LogEventDTO
from app.services import log_events as log_event_service
from tests.conftest import upgrade


def _seed_user(engine: Engine, tz_name: str) -> uuid.UUID:
    """Create a user with a profile in ``tz_name`` and return the user id."""

    factory = create_session_factory(engine)
    with factory() as session:
        user = User()
        session.add(user)
        session.flush()
        session.add(UserProfile(user_id=user.id, timezone=tz_name))
        session.commit()
        return user.id


def _seed_event_at(engine: Engine, user_id: uuid.UUID, created_at: datetime) -> uuid.UUID:
    """Insert a pending event stamped at ``created_at`` and return its id."""

    factory = create_session_factory(engine)
    with factory() as session:
        event = LogEvent(
            user_id=user_id,
            raw_text="seed event",
            status="pending",
            created_at=created_at,
        )
        session.add(event)
        session.commit()
        return event.id


def test_created_at_round_trips_as_utc_on_postgres(pg_engine: Engine) -> None:
    """``created_at`` stores and reads back as the same UTC instant, tz-aware.

    Writes an offset-bearing instant and confirms Postgres' ``timestamptz`` returns
    it tz-aware and pointing at the same moment — no naive drift, no local-zone
    reinterpretation.
    """

    upgrade(pg_engine, "head")
    user_id = _seed_user(pg_engine, "America/New_York")

    instant = datetime(2026, 6, 16, 1, 0, tzinfo=UTC)
    event_id = _seed_event_at(pg_engine, user_id, instant)

    factory = create_session_factory(pg_engine)
    with factory() as session:
        event = session.get(LogEvent, event_id)
        assert event is not None
        assert event.created_at.tzinfo is not None, "created_at read back naive"
        assert event.created_at == instant
        assert event.updated_at.tzinfo is not None, "updated_at read back naive"


def test_dto_serializes_timezone_aware_on_postgres(pg_engine: Engine) -> None:
    """The event DTO serializes both timestamps with an explicit UTC offset."""

    upgrade(pg_engine, "head")
    user_id = _seed_user(pg_engine, "America/New_York")
    event_id = _seed_event_at(pg_engine, user_id, datetime(2026, 6, 16, 1, 0, tzinfo=UTC))

    factory = create_session_factory(pg_engine)
    with factory() as session:
        event = session.get(LogEvent, event_id)
        assert event is not None
        body = LogEventDTO.model_validate(event).model_dump(mode="json")

    for field in ("created_at", "updated_at"):
        raw = body[field]
        assert raw.endswith("Z") or raw.endswith("+00:00"), f"{field} not tz-aware: {raw!r}"
        parsed = datetime.fromisoformat(raw)
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)


def test_previous_local_evening_buckets_to_prior_day_on_postgres(pg_engine: Engine) -> None:
    """A prior-evening entry buckets under the prior local day, not "Today".

    America/New_York: 2026-06-16 01:00 UTC is 2026-06-15 21:00 EDT — 9pm the prior
    local day. The bucketing query (run against Postgres ``timestamptz``) must place
    it on 2026-06-15, never the 2026-06-16 local day that shares its UTC date.
    """

    upgrade(pg_engine, "head")
    user_id = _seed_user(pg_engine, "America/New_York")
    event_id = _seed_event_at(pg_engine, user_id, datetime(2026, 6, 16, 1, 0, tzinfo=UTC))

    factory = create_session_factory(pg_engine)
    with factory() as session:
        user = session.get(User, user_id)
        assert user is not None
        today = log_event_service.list_events_for_day(session, user_id, user, date(2026, 6, 16))
        prior = log_event_service.list_events_for_day(session, user_id, user, date(2026, 6, 15))

    assert [e.id for e in today] == [], "prior-evening entry leaked into Today on Postgres"
    assert [e.id for e in prior] == [event_id]


def test_half_hour_offset_zone_buckets_by_local_midnight_on_postgres(pg_engine: Engine) -> None:
    """Asia/Kolkata (UTC+5:30) buckets two midnight-straddling entries correctly.

    - 2026-06-15 18:15 UTC → 2026-06-15 23:45 IST → local day 2026-06-15
    - 2026-06-15 18:45 UTC → 2026-06-16 00:15 IST → local day 2026-06-16
    """

    upgrade(pg_engine, "head")
    user_id = _seed_user(pg_engine, "Asia/Kolkata")
    before = _seed_event_at(pg_engine, user_id, datetime(2026, 6, 15, 18, 15, tzinfo=UTC))
    after = _seed_event_at(pg_engine, user_id, datetime(2026, 6, 15, 18, 45, tzinfo=UTC))

    factory = create_session_factory(pg_engine)
    with factory() as session:
        user = session.get(User, user_id)
        assert user is not None
        day15 = log_event_service.list_events_for_day(session, user_id, user, date(2026, 6, 15))
        day16 = log_event_service.list_events_for_day(session, user_id, user, date(2026, 6, 16))

    assert [e.id for e in day15] == [before]
    assert [e.id for e in day16] == [after]
