"""FTY-328 partial-resolution backend state/read/answer tests.

FTY-329 will teach the estimator to emit ``partially_resolved``. Until then these
tests seed the contract state directly and prove the backend can represent, read,
count, and answer it without mutating resolved siblings or duplicating rows.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.enums import DerivedItemStatus, LogEventStatus
from app.models.derived import ClarificationAnswer, ClarificationQuestion, DerivedFoodItem
from app.models.identity import User, UserProfile
from app.models.log_events import LogEvent
from app.services import clarification as clarification_service
from app.services import daily_summary as daily_summary_service
from app.services import log_events as log_event_service
from tests.conftest import RecordingEnqueuer, upgrade


def _register(client: TestClient, email: str) -> tuple[str, str]:
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "a-good-password"},
    )
    assert resp.status_code == 201
    body = resp.json()
    return body["user"]["id"], f"Bearer {body['token']['access_token']}"


def _seed_partial_event(db_engine: Engine, user_id: str) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """Seed one resolved sibling, one unresolved component, and its open question."""

    factory = create_session_factory(db_engine)
    with factory() as session:
        event = LogEvent(
            user_id=uuid.UUID(user_id),
            raw_text="peanut butter toast and milk amount pending",
            status=LogEventStatus.PARTIALLY_RESOLVED,
            created_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
        )
        session.add(event)
        session.flush()

        resolved = DerivedFoodItem(
            log_event_id=event.id,
            user_id=uuid.UUID(user_id),
            name="peanut butter toast",
            quantity_text="1 slice",
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
        unresolved = DerivedFoodItem(
            log_event_id=event.id,
            user_id=uuid.UUID(user_id),
            name="milk",
            quantity_text="",
            status=DerivedItemStatus.UNRESOLVED,
        )
        session.add_all([resolved, unresolved])
        session.flush()

        session.add(
            ClarificationQuestion(
                log_event_id=event.id,
                user_id=uuid.UUID(user_id),
                question_text="How much milk?",
                options=["a splash", "1/2 cup", "1 cup"],
                derived_food_item_id=unresolved.id,
                position=0,
            )
        )
        session.commit()
        return event.id, resolved.id, unresolved.id


def _answer_url(user_id: str, event_id: uuid.UUID) -> str:
    return f"/api/users/{user_id}/log-events/{event_id}/clarification/answers"


def _answer_count(db_engine: Engine, event_id: uuid.UUID) -> int:
    factory = create_session_factory(db_engine)
    with factory() as session:
        return (
            session.scalar(
                select(func.count())
                .select_from(ClarificationAnswer)
                .where(ClarificationAnswer.log_event_id == event_id)
            )
            or 0
        )


def _assert_seeded_partial_reads(
    client: TestClient,
    user_id: str,
    auth: str,
    event_id: uuid.UUID,
    resolved_id: uuid.UUID,
) -> str:
    """Assert partial read/count semantics and return the open question id."""

    single = client.get(
        f"/api/users/{user_id}/log-events/{event_id}",
        headers={"Authorization": auth},
    )
    listed = client.get(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        params={"day": "2026-07-10"},
    )
    entries = client.get(
        f"/api/users/{user_id}/log-events/by-date",
        headers={"Authorization": auth},
        params={"day": "2026-07-10"},
    )
    summary = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": "2026-07-10"},
    )
    clarification = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/clarification",
        headers={"Authorization": auth},
    )

    assert single.status_code == listed.status_code == entries.status_code == 200
    assert summary.status_code == clarification.status_code == 200
    assert single.json()["status"] == "partially_resolved"
    assert [event["id"] for event in listed.json()] == [str(event_id)]
    assert entries.json()[0]["event"]["status"] == "partially_resolved"
    assert [item["id"] for item in entries.json()[0]["items"]] == [str(resolved_id)]
    assert summary.json()["intake"]["calories"] == 180.0
    assert summary.json()["has_intake"] is True
    assert summary.json()["uncounted_entries"] == 1

    question = clarification.json()["questions"][0]
    assert question == {
        "id": question["id"],
        "text": "How much milk?",
        "options": ["a splash", "1/2 cup", "1 cup"],
    }
    assert "derived_food_item_id" not in question
    return str(question["id"])


def _assert_answer_preserved_partial_siblings(
    db_engine: Engine,
    event_id: uuid.UUID,
    resolved_id: uuid.UUID,
    unresolved_id: uuid.UUID,
    question_id: str,
) -> None:
    """The answer commit leaves existing item rows exactly one-per-component."""

    factory = create_session_factory(db_engine)
    with factory() as session:
        event = session.get(LogEvent, event_id)
        assert event is not None
        assert event.raw_text == "peanut butter toast and milk amount pending"
        foods = list(
            session.scalars(
                select(DerivedFoodItem)
                .where(DerivedFoodItem.log_event_id == event_id)
                .order_by(DerivedFoodItem.id.asc())
            )
        )
        assert {food.id for food in foods} == {resolved_id, unresolved_id}
        resolved = session.get(DerivedFoodItem, resolved_id)
        unresolved = session.get(DerivedFoodItem, unresolved_id)
        assert resolved is not None and unresolved is not None
        assert resolved.status == DerivedItemStatus.RESOLVED
        assert resolved.calories == 180.0
        assert unresolved.status == DerivedItemStatus.UNRESOLVED
        carrier = session.scalars(
            select(ClarificationQuestion).where(ClarificationQuestion.id == uuid.UUID(question_id))
        ).one()
        assert carrier.derived_food_item_id == unresolved_id


def _resolve_open_component(
    db_engine: Engine,
    event_id: uuid.UUID,
    unresolved_id: uuid.UUID,
) -> None:
    """Simulate FTY-329 resolving only the answered component."""

    factory = create_session_factory(db_engine)
    with factory() as session:
        event = session.get(LogEvent, event_id)
        unresolved = session.get(DerivedFoodItem, unresolved_id)
        assert event is not None and unresolved is not None
        unresolved.status = DerivedItemStatus.RESOLVED
        unresolved.quantity_text = "1 cup"
        unresolved.amount = 1.0
        unresolved.unit = "cup"
        unresolved.grams = 244.0
        unresolved.calories = 120.0
        unresolved.protein_g = 8.0
        unresolved.carbs_g = 12.0
        unresolved.fat_g = 5.0
        unresolved.calories_estimated = 120.0
        unresolved.protein_g_estimated = 8.0
        unresolved.carbs_g_estimated = 12.0
        unresolved.fat_g_estimated = 5.0
        event.status = LogEventStatus.COMPLETED
        session.add_all([event, unresolved])
        session.commit()


def _assert_completed_counts_and_items(
    client: TestClient,
    user_id: str,
    auth: str,
    resolved_id: uuid.UUID,
    unresolved_id: uuid.UUID,
) -> None:
    completed_summary = client.get(
        f"/api/users/{user_id}/daily-summary",
        headers={"Authorization": auth},
        params={"day": "2026-07-10"},
    )
    completed_entries = client.get(
        f"/api/users/{user_id}/log-events/by-date",
        headers={"Authorization": auth},
        params={"day": "2026-07-10"},
    )

    assert completed_summary.json()["intake"]["calories"] == 300.0
    assert completed_summary.json()["uncounted_entries"] == 0
    assert {item["id"] for item in completed_entries.json()[0]["items"]} == {
        str(resolved_id),
        str(unresolved_id),
    }


def test_seeded_partial_event_reads_counts_and_answers_without_sibling_drift(
    client: TestClient,
    db_engine: Engine,
    enqueuer: RecordingEnqueuer,
) -> None:
    """Pinned FTY-278 clauses: partial reads, per-question count, idempotent answer."""

    user_id, auth = _register(client, "partial-flow@example.com")
    event_id, resolved_id, unresolved_id = _seed_partial_event(db_engine, user_id)
    question_id = _assert_seeded_partial_reads(client, user_id, auth, event_id, resolved_id)

    fresh = client.post(
        _answer_url(user_id, event_id),
        headers={"Authorization": auth},
        json={"question_id": question_id, "answer": "1 cup"},
    )

    assert fresh.status_code == 201
    assert fresh.json()["id"] == str(event_id)
    assert fresh.json()["status"] == "processing"
    assert [call[0] for call in enqueuer.calls] == [event_id]
    _assert_answer_preserved_partial_siblings(
        db_engine, event_id, resolved_id, unresolved_id, question_id
    )

    replay = client.post(
        _answer_url(user_id, event_id),
        headers={"Authorization": auth},
        json={"question_id": question_id, "answer": "2 cups"},
    )

    assert replay.status_code == 200
    assert replay.json()["status"] == "processing"
    assert _answer_count(db_engine, event_id) == 1
    assert [call[0] for call in enqueuer.calls] == [event_id]

    _resolve_open_component(db_engine, event_id, unresolved_id)

    late_replay = client.post(
        _answer_url(user_id, event_id),
        headers={"Authorization": auth},
        json={"question_id": question_id, "answer": "1 cup"},
    )

    assert late_replay.status_code == 200
    assert late_replay.json()["status"] == "completed"
    assert [call[0] for call in enqueuer.calls] == [event_id]
    _assert_completed_counts_and_items(client, user_id, auth, resolved_id, unresolved_id)
    assert _answer_count(db_engine, event_id) == 1


def test_item_scoped_question_rejects_full_raw_diary_text(
    client: TestClient,
    db_engine: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Question rows fail closed if they echo the full raw diary phrase."""

    user_id, _auth = _register(client, "partial-redaction@example.com")
    raw_text = "private diary phrase with exact supplement detail"
    factory = create_session_factory(db_engine)

    with factory() as session:
        event = LogEvent(
            user_id=uuid.UUID(user_id),
            raw_text=raw_text,
            status=LogEventStatus.PARTIALLY_RESOLVED,
            created_at=datetime(2026, 7, 10, 12, 0, tzinfo=UTC),
        )
        session.add(event)
        session.flush()
        item = DerivedFoodItem(
            log_event_id=event.id,
            user_id=uuid.UUID(user_id),
            name="supplement",
            quantity_text="",
            status=DerivedItemStatus.UNRESOLVED,
        )
        session.add(item)
        session.commit()
        event_id = event.id
        item_id = item.id

    with factory() as session:
        session.add(
            ClarificationQuestion(
                log_event_id=event_id,
                user_id=uuid.UUID(user_id),
                question_text=f"How much of {raw_text}?",
                options=[],
                derived_food_item_id=item_id,
                position=0,
            )
        )
        with caplog.at_level("DEBUG"), pytest.raises(ValueError) as exc_info:
            session.commit()
        assert raw_text not in str(exc_info.value)
        assert raw_text not in caplog.text
        session.rollback()

    with factory() as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(ClarificationQuestion)
                .where(ClarificationQuestion.log_event_id == event_id)
            )
            == 0
        )


def test_partial_resolution_state_machine_and_counts_on_postgres(pg_engine: Engine) -> None:
    """Postgres parity for the seeded partial state, count, and answer idempotency."""

    upgrade(pg_engine, "head")
    factory = create_session_factory(pg_engine)
    with factory() as session:
        created_user = User()
        session.add(created_user)
        session.flush()
        session.add(UserProfile(user_id=created_user.id, timezone="UTC"))
        session.commit()
        user_id = created_user.id

    event_id, resolved_id, unresolved_id = _seed_partial_event(pg_engine, str(user_id))

    with factory() as session:
        loaded_user = session.get(User, user_id)
        assert loaded_user is not None
        entries = log_event_service.list_entries_for_day(
            session, user_id, loaded_user, date(2026, 7, 10)
        )
        summary = daily_summary_service.get_daily_summary(
            session, user_id, loaded_user, date(2026, 7, 10)
        )
        questions = log_event_service.list_clarification_questions(
            session, user_id, loaded_user, event_id
        )

        assert [item.id for item in entries[0].items] == [resolved_id]
        assert summary.intake.calories == 180.0
        assert summary.uncounted_entries == 1
        assert len(questions) == 1
        assert questions[0].derived_food_item_id == unresolved_id

        event, resolved = clarification_service.answer_clarification_question(
            session, user_id, loaded_user, event_id, questions[0].id, "1 cup"
        )
        assert resolved is True
        assert LogEventStatus(event.status) is LogEventStatus.PROCESSING

    with factory() as session:
        loaded_user = session.get(User, user_id)
        assert loaded_user is not None
        question = session.scalars(
            select(ClarificationQuestion).where(ClarificationQuestion.log_event_id == event_id)
        ).one()
        event, resolved = clarification_service.answer_clarification_question(
            session, user_id, loaded_user, event_id, question.id, "2 cups"
        )

        assert resolved is False
        assert LogEventStatus(event.status) is LogEventStatus.PROCESSING
        assert _answer_count(pg_engine, event_id) == 1
        foods = list(
            session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
        )
        assert {food.id for food in foods} == {resolved_id, unresolved_id}
