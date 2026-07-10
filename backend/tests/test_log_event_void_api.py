"""Soft-void (delete) a logged food entry — backend capability (FTY-321).

``DELETE /api/users/{user_id}/log-events/{event_id}`` voids an event: it — and
every derived item hanging off it — disappears from every read model and stops
counting toward the daily summary, while the underlying rows are **retained**
(soft void), preserving the append-only audit/provenance stance.

These tests prove the acceptance criteria: read-model exclusion (list / by-date /
single GET / derived items / daily totals), void from any status, clarify-on-void
fails closed, idempotency, the ``404`` fail-closed cases (unknown / cross-user),
no hard deletion, and the exact-contribution drop in daily totals — exercised
against SQLite and (opt-in) Postgres.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.enums import DerivedItemStatus, LogEventStatus, SourceType
from app.models.derived import ClarificationQuestion, DerivedExerciseItem, DerivedFoodItem
from app.models.food_sources import EvidenceSource
from app.models.identity import User, UserProfile
from app.models.log_events import LogEvent
from app.services import daily_summary as daily_summary_service
from app.services import log_events as log_event_service
from tests.conftest import upgrade


def _register(client: TestClient, email: str) -> tuple[str, str]:
    """Register a user, returning ``(user_id, auth_header_value)``."""

    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "a-good-password"},
    )
    assert resp.status_code == 201
    body = resp.json()
    return body["user"]["id"], f"Bearer {body['token']['access_token']}"


def _seed_event(
    db_engine: Engine,
    user_id: str,
    *,
    created_at: datetime,
    raw_text: str = "seed event",
    status: LogEventStatus = LogEventStatus.COMPLETED,
) -> uuid.UUID:
    factory = create_session_factory(db_engine)
    with factory() as session:
        event = LogEvent(
            user_id=uuid.UUID(user_id),
            raw_text=raw_text,
            status=status,
            created_at=created_at,
        )
        session.add(event)
        session.commit()
        return event.id


def _seed_food_item(
    db_engine: Engine,
    user_id: str,
    event_id: uuid.UUID,
    *,
    name: str = "white rice",
    status: DerivedItemStatus = DerivedItemStatus.RESOLVED,
    calories: float | None = 205.0,
) -> uuid.UUID:
    factory = create_session_factory(db_engine)
    with factory() as session:
        item = DerivedFoodItem(
            log_event_id=event_id,
            user_id=uuid.UUID(user_id),
            name=name,
            quantity_text="1 serving",
            unit=None,
            amount=1.0,
            status=status,
            grams=150.0,
            calories=calories,
            protein_g=4.3 if calories is not None else None,
            carbs_g=44.5 if calories is not None else None,
            fat_g=0.4 if calories is not None else None,
            calories_estimated=calories,
            protein_g_estimated=4.3 if calories is not None else None,
            carbs_g_estimated=44.5 if calories is not None else None,
            fat_g_estimated=0.4 if calories is not None else None,
        )
        session.add(item)
        session.commit()
        return item.id


def _seed_exercise_item(
    db_engine: Engine,
    user_id: str,
    event_id: uuid.UUID,
    *,
    active_calories: float | None = 120.0,
) -> uuid.UUID:
    factory = create_session_factory(db_engine)
    with factory() as session:
        item = DerivedExerciseItem(
            log_event_id=event_id,
            user_id=uuid.UUID(user_id),
            name="walking",
            quantity_text="30 minutes",
            unit="minutes",
            amount=30.0,
            status=DerivedItemStatus.RESOLVED,
            active_calories=active_calories,
            active_calories_estimated=active_calories,
        )
        session.add(item)
        session.commit()
        return item.id


def _seed_question(db_engine: Engine, user_id: str, event_id: uuid.UUID) -> uuid.UUID:
    factory = create_session_factory(db_engine)
    with factory() as session:
        question = ClarificationQuestion(
            log_event_id=event_id,
            user_id=uuid.UUID(user_id),
            question_text="How much peanut butter?",
            options=["1 tsp", "1 tbsp"],
            position=0,
        )
        session.add(question)
        session.commit()
        return question.id


def _daily_intake(client: TestClient, user_id: str, auth: str, day: str) -> dict[str, Any]:
    resp = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": day},
    )
    assert resp.status_code == 200
    result: dict[str, Any] = resp.json()
    return result


# ---------------------------------------------------------------------------
# Read-model exclusion
# ---------------------------------------------------------------------------


def test_void_excludes_event_from_every_read_model(client: TestClient, db_engine: Engine) -> None:
    """A voided event drops from list / by-date / single GET and the daily totals."""

    user_id, auth = _register(client, "void-reads@example.com")
    event_id = _seed_event(db_engine, user_id, created_at=datetime(2026, 6, 20, 12, 0, tzinfo=UTC))
    _seed_food_item(db_engine, user_id, event_id)
    _seed_exercise_item(db_engine, user_id, event_id)

    # Present in every read before voiding.
    assert _daily_intake(client, user_id, auth, "2026-06-20")["intake"]["calories"] == 205.0
    before_list = client.get(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        params={"day": "2026-06-20"},
    )
    assert [e["id"] for e in before_list.json()] == [str(event_id)]

    resp = client.delete(
        f"/api/users/{user_id}/log-events/{event_id}", headers={"Authorization": auth}
    )
    assert resp.status_code == 204
    assert resp.content == b""

    # Gone from list, by-date, single GET, and the daily totals.
    after_list = client.get(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        params={"day": "2026-06-20"},
    )
    assert after_list.json() == []

    by_date = client.get(
        f"/api/users/{user_id}/log-events/by-date",
        headers={"Authorization": auth},
        params={"day": "2026-06-20"},
    )
    assert by_date.json() == []

    single = client.get(
        f"/api/users/{user_id}/log-events/{event_id}", headers={"Authorization": auth}
    )
    assert single.status_code == 404

    summary = _daily_intake(client, user_id, auth, "2026-06-20")
    assert summary["intake"]["calories"] == 0.0
    assert summary["intake"]["protein_g"] == 0.0
    assert summary["has_intake"] is False
    assert summary["exercise"]["active_calories"] == 0.0


def test_void_drops_daily_totals_by_exactly_the_voided_contribution(
    client: TestClient, db_engine: Engine
) -> None:
    """Voiding one entry leaves exactly the surviving entries' totals — no more, no less."""

    user_id, auth = _register(client, "void-math@example.com")
    keep_event = _seed_event(db_engine, user_id, created_at=datetime(2026, 6, 20, 9, 0, tzinfo=UTC))
    void_event = _seed_event(
        db_engine, user_id, created_at=datetime(2026, 6, 20, 12, 0, tzinfo=UTC)
    )
    _seed_food_item(db_engine, user_id, keep_event, calories=100.0)
    _seed_food_item(db_engine, user_id, void_event, calories=205.0)

    before = _daily_intake(client, user_id, auth, "2026-06-20")
    assert before["intake"]["calories"] == 305.0

    client.delete(
        f"/api/users/{user_id}/log-events/{void_event}", headers={"Authorization": auth}
    ).raise_for_status()

    after = _daily_intake(client, user_id, auth, "2026-06-20")
    # Exactly the surviving entry's contribution remains; the voided 205 kcal is gone.
    assert after["intake"]["calories"] == 100.0
    assert after["has_intake"] is True


def test_void_excludes_needs_clarification_from_uncounted_entries(
    client: TestClient, db_engine: Engine
) -> None:
    """A voided ``needs_clarification`` event stops inflating ``uncounted_entries``."""

    user_id, auth = _register(client, "void-uncounted@example.com")
    event_id = _seed_event(
        db_engine,
        user_id,
        created_at=datetime(2026, 6, 20, 12, 0, tzinfo=UTC),
        status=LogEventStatus.NEEDS_CLARIFICATION,
    )
    _seed_question(db_engine, user_id, event_id)

    assert _daily_intake(client, user_id, auth, "2026-06-20")["uncounted_entries"] == 1

    client.delete(
        f"/api/users/{user_id}/log-events/{event_id}", headers={"Authorization": auth}
    ).raise_for_status()

    assert _daily_intake(client, user_id, auth, "2026-06-20")["uncounted_entries"] == 0


# ---------------------------------------------------------------------------
# Void from any status; clarify-on-void fails closed
# ---------------------------------------------------------------------------


def test_void_works_for_failed_event(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = _register(client, "void-failed@example.com")
    event_id = _seed_event(
        db_engine,
        user_id,
        created_at=datetime(2026, 6, 20, 12, 0, tzinfo=UTC),
        status=LogEventStatus.FAILED,
    )

    resp = client.delete(
        f"/api/users/{user_id}/log-events/{event_id}", headers={"Authorization": auth}
    )
    assert resp.status_code == 204
    assert (
        client.get(
            f"/api/users/{user_id}/log-events/{event_id}", headers={"Authorization": auth}
        ).status_code
        == 404
    )


def test_void_needs_clarification_makes_clarify_read_and_answer_fail_closed(
    client: TestClient, db_engine: Engine
) -> None:
    """Reading or answering a clarification on a voided event returns 404."""

    user_id, auth = _register(client, "void-clarify@example.com")
    event_id = _seed_event(
        db_engine,
        user_id,
        created_at=datetime(2026, 6, 20, 12, 0, tzinfo=UTC),
        status=LogEventStatus.NEEDS_CLARIFICATION,
    )
    question_id = _seed_question(db_engine, user_id, event_id)

    # Readable before the void.
    assert (
        client.get(
            f"/api/users/{user_id}/log-events/{event_id}/clarification",
            headers={"Authorization": auth},
        ).status_code
        == 200
    )

    client.delete(
        f"/api/users/{user_id}/log-events/{event_id}", headers={"Authorization": auth}
    ).raise_for_status()

    read = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/clarification",
        headers={"Authorization": auth},
    )
    answer = client.post(
        f"/api/users/{user_id}/log-events/{event_id}/clarification/answers",
        headers={"Authorization": auth},
        json={"question_id": str(question_id), "answer": "1 tbsp"},
    )

    assert read.status_code == 404
    assert answer.status_code == 404


# ---------------------------------------------------------------------------
# Idempotency, fail-closed, and soft-delete retention
# ---------------------------------------------------------------------------


def test_void_is_idempotent(client: TestClient, db_engine: Engine) -> None:
    """Repeating the DELETE succeeds identically and never re-stamps ``voided_at``."""

    user_id, auth = _register(client, "void-idempotent@example.com")
    event_id = _seed_event(db_engine, user_id, created_at=datetime(2026, 6, 20, 12, 0, tzinfo=UTC))

    first = client.delete(
        f"/api/users/{user_id}/log-events/{event_id}", headers={"Authorization": auth}
    )
    assert first.status_code == 204

    factory = create_session_factory(db_engine)
    with factory() as session:
        first_event = session.get(LogEvent, event_id)
        assert first_event is not None
        first_voided_at = first_event.voided_at
    assert first_voided_at is not None

    second = client.delete(
        f"/api/users/{user_id}/log-events/{event_id}", headers={"Authorization": auth}
    )
    assert second.status_code == 204

    with factory() as session:
        second_event = session.get(LogEvent, event_id)
        assert second_event is not None
        second_voided_at = second_event.voided_at
    # Void is set once — the terminal marker is not moved by a repeat delete.
    assert second_voided_at == first_voided_at


def test_void_unknown_id_is_not_found(client: TestClient) -> None:
    user_id, auth = _register(client, "void-unknown@example.com")

    resp = client.delete(
        f"/api/users/{user_id}/log-events/{uuid.uuid4()}", headers={"Authorization": auth}
    )

    assert resp.status_code == 404


def test_void_cross_user_fails_closed(client: TestClient, db_engine: Engine) -> None:
    """Another user's event id returns 404 (no existence oracle) and stays live."""

    alice_id, alice_auth = _register(client, "void-alice@example.com")
    bob_id, bob_auth = _register(client, "void-bob@example.com")
    bob_event = _seed_event(db_engine, bob_id, created_at=datetime(2026, 6, 20, 12, 0, tzinfo=UTC))

    via_bob_path = client.delete(
        f"/api/users/{bob_id}/log-events/{bob_event}", headers={"Authorization": alice_auth}
    )
    via_alice_path = client.delete(
        f"/api/users/{alice_id}/log-events/{bob_event}", headers={"Authorization": alice_auth}
    )

    assert via_bob_path.status_code == 404
    assert via_alice_path.status_code == 404
    # Bob's event was not voided by Alice's attempt.
    assert (
        client.get(
            f"/api/users/{bob_id}/log-events/{bob_event}", headers={"Authorization": bob_auth}
        ).status_code
        == 200
    )


def test_void_requires_authentication(client: TestClient, db_engine: Engine) -> None:
    user_id, _auth = _register(client, "void-noauth@example.com")
    event_id = _seed_event(db_engine, user_id, created_at=datetime(2026, 6, 20, 12, 0, tzinfo=UTC))

    missing = client.delete(f"/api/users/{user_id}/log-events/{event_id}")
    bad = client.delete(
        f"/api/users/{user_id}/log-events/{event_id}",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert missing.status_code == 401
    assert bad.status_code == 401


def test_void_retains_rows_no_hard_deletion(client: TestClient, db_engine: Engine) -> None:
    """The event and its derived rows remain in storage with the void marker set."""

    user_id, auth = _register(client, "void-retain@example.com")
    event_id = _seed_event(db_engine, user_id, created_at=datetime(2026, 6, 20, 12, 0, tzinfo=UTC))
    food_id = _seed_food_item(db_engine, user_id, event_id)
    exercise_id = _seed_exercise_item(db_engine, user_id, event_id)

    client.delete(
        f"/api/users/{user_id}/log-events/{event_id}", headers={"Authorization": auth}
    ).raise_for_status()

    factory = create_session_factory(db_engine)
    with factory() as session:
        event = session.get(LogEvent, event_id)
        assert event is not None
        assert event.voided_at is not None
        # The event keeps its pre-void status; void is an orthogonal marker.
        assert event.status == LogEventStatus.COMPLETED
        assert session.get(DerivedFoodItem, food_id) is not None
        assert session.get(DerivedExerciseItem, exercise_id) is not None


def test_void_round_trips_on_postgres(pg_engine: Engine) -> None:
    """Void → read-model exclusion + row retention exercise the production datastore."""

    upgrade(pg_engine, "head")
    factory = create_session_factory(pg_engine)
    with factory() as session:
        user = User()
        session.add(user)
        session.flush()
        session.add(UserProfile(user_id=user.id, timezone="UTC"))
        event = LogEvent(
            user_id=user.id,
            raw_text="postgres mislog",
            status=LogEventStatus.COMPLETED,
            created_at=datetime(2026, 6, 20, 12, 0, tzinfo=UTC),
        )
        session.add(event)
        session.flush()
        item = DerivedFoodItem(
            log_event_id=event.id,
            user_id=user.id,
            name="white rice",
            quantity_text="1 serving",
            amount=1.0,
            status=DerivedItemStatus.RESOLVED,
            grams=150.0,
            calories=205.0,
            protein_g=4.3,
            carbs_g=44.5,
            fat_g=0.4,
            calories_estimated=205.0,
            protein_g_estimated=4.3,
            carbs_g_estimated=44.5,
            fat_g_estimated=0.4,
        )
        session.add(item)
        session.add(
            EvidenceSource(
                user_id=user.id,
                log_event_id=event.id,
                derived_food_item_id=item.id,
                product_id=None,
                source_type=SourceType.TRUSTED_NUTRITION_DATABASE,
                source_ref="usda_fdc:168880",
                content_hash="0" * 64,
                fetched_at=datetime.now(UTC),
                calories_per_100g=130.0,
                protein_per_100g=2.7,
                carbs_per_100g=28.0,
                fat_per_100g=0.3,
            )
        )
        session.commit()
        user_id = user.id
        event_id = event.id
        item_id = item.id

    # Counts before the void.
    with factory() as session:
        loaded = session.get(User, user_id)
        assert loaded is not None
        before = daily_summary_service.get_daily_summary(
            session, user_id, loaded, date(2026, 6, 20)
        )
        assert before.intake.calories == 205.0
        log_event_service.void_event(session, user_id, loaded, event_id)

    # Excluded from the read model, rows retained with the marker set.
    with factory() as session:
        loaded = session.get(User, user_id)
        assert loaded is not None
        after = daily_summary_service.get_daily_summary(session, user_id, loaded, date(2026, 6, 20))
        assert after.intake.calories == 0.0
        assert after.has_intake is False
        entries = log_event_service.list_entries_for_day(
            session, user_id, loaded, date(2026, 6, 20)
        )
        assert entries == []

        retained_event = session.get(LogEvent, event_id)
        assert retained_event is not None
        assert retained_event.voided_at is not None
        assert session.get(DerivedFoodItem, item_id) is not None
