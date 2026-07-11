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


def _add_followup_question(
    db_engine: Engine,
    event_id: uuid.UUID,
    user_id: uuid.UUID,
    component_id: uuid.UUID,
) -> None:
    """Simulate a fresh clarification round on the same still-unresolved component.

    The answer flow retains answered question rows
    (``_persist_clarification_questions`` deletes only *unanswered* rows), so a new
    round adds a second open question on the SAME component while the prior answered
    row survives — two question rows linked to one unresolved component (FTY-349).
    The question text names only the sanitized component ``name`` (never the raw
    diary phrase), matching the FTY-278 redaction gate.
    """

    factory = create_session_factory(db_engine)
    with factory() as session:
        session.add(
            ClarificationQuestion(
                log_event_id=event_id,
                user_id=user_id,
                question_text="Was the milk whole or skim?",
                options=["whole", "skim", "2%"],
                derived_food_item_id=component_id,
                position=1,
            )
        )
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


def _seed_pg_user(pg_engine: Engine) -> uuid.UUID:
    """Create one user with a UTC profile on the Postgres engine."""

    factory = create_session_factory(pg_engine)
    with factory() as session:
        created_user = User()
        session.add(created_user)
        session.flush()
        session.add(UserProfile(user_id=created_user.id, timezone="UTC"))
        session.commit()
        return created_user.id


def test_daily_summary_no_dip_predicate_on_postgres(pg_engine: Engine) -> None:
    """FTY-349 Postgres parity for the scoped-re-estimate read-model predicate.

    On the production engine: (a) the committed sibling stays in ``intake`` /
    range / ``has_intake`` **and in the ``/log-events/by-date`` item read** and the
    answered-but-unresolved question stays in ``uncounted_entries`` while the **real
    answer flow** holds the event at ``processing``; (b) a first-pass ``processing``
    event with no committed resolved item contributes nothing; (c) resolving the
    open component raises the total by exactly the new item with the sibling
    unchanged.
    """

    upgrade(pg_engine, "head")
    user_id = _seed_pg_user(pg_engine)
    event_id, resolved_id, unresolved_id = _seed_partial_event(pg_engine, str(user_id))
    day = date(2026, 7, 10)
    factory = create_session_factory(pg_engine)

    def _read_summaries() -> tuple[float, bool, int]:
        """Read the single-day and range models, assert parity, return the day."""

        with factory() as session:
            loaded_user = session.get(User, user_id)
            assert loaded_user is not None
            single = daily_summary_service.get_daily_summary(session, user_id, loaded_user, day)
            ranged = daily_summary_service.get_daily_summaries(
                session, user_id, loaded_user, day, day
            )
            assert ranged == [single]
            return single.intake.calories, single.has_intake, single.uncounted_entries

    def _by_date_item_ids() -> set[uuid.UUID]:
        """Item ids the ``/log-events/by-date`` day-listing read surfaces for the event."""

        with factory() as session:
            loaded_user = session.get(User, user_id)
            assert loaded_user is not None
            entries = log_event_service.list_entries_for_day(session, user_id, loaded_user, day)
            event_entries = [entry for entry in entries if entry.event.id == event_id]
            assert len(event_entries) == 1
            return {item.id for item in event_entries[0].items}

    # BEFORE: the pinned partial state — sibling counted, one open question, and the
    # committed sibling on the timeline.
    assert _read_summaries() == (180.0, True, 1)
    assert _by_date_item_ids() == {resolved_id}

    # DURING: the real answer flow commits the ClarificationAnswer row in the same
    # transaction that flips the event to ``processing``. The question is answered
    # but its component is still unresolved — nothing may dip, and the by-date read
    # must keep the committed sibling on the timeline.
    with factory() as session:
        loaded_user = session.get(User, user_id)
        assert loaded_user is not None
        questions = log_event_service.list_clarification_questions(
            session, user_id, loaded_user, event_id
        )
        event, resolved = clarification_service.answer_clarification_question(
            session, user_id, loaded_user, event_id, questions[0].id, "1 cup"
        )
        assert resolved is True
        assert LogEventStatus(event.status) is LogEventStatus.PROCESSING
    assert _read_summaries() == (180.0, True, 1)
    assert _by_date_item_ids() == {resolved_id}

    # A first-pass ``processing`` event (no committed resolved item) on the same
    # day still contributes nothing to any surface — the totals stay unchanged.
    with factory() as session:
        first_pass = LogEvent(
            user_id=user_id,
            raw_text="mystery smoothie",
            status=LogEventStatus.PROCESSING,
            created_at=datetime(2026, 7, 10, 13, 0, tzinfo=UTC),
        )
        session.add(first_pass)
        session.flush()
        session.add(
            DerivedFoodItem(
                log_event_id=first_pass.id,
                user_id=user_id,
                name="smoothie",
                quantity_text="",
                status=DerivedItemStatus.UNRESOLVED,
            )
        )
        session.commit()
    assert _read_summaries() == (180.0, True, 1)

    # AFTER: the open component resolves and the event completes (FTY-329's
    # terminal write). The total rises by exactly the newly-resolved 120 kcal —
    # the sibling is never re-added — and the uncounted entry drops. Both items now
    # surface on the by-date timeline, the sibling never duplicated.
    _resolve_open_component(pg_engine, event_id, unresolved_id)
    assert _read_summaries() == (300.0, True, 0)
    assert _by_date_item_ids() == {resolved_id, unresolved_id}


def test_first_pass_processing_commit_window_is_excluded_on_postgres(pg_engine: Engine) -> None:
    """FTY-349 Postgres parity: the worker's real two-commit completion window.

    The estimation worker commits a first-pass event's ``resolved`` derived rows in
    the same transaction as the run/job status and then transitions the event
    ``processing → completed`` in a *second* commit
    (``app.estimator.processing._finalize``). Between those commits the event is
    externally visible as ``processing`` **with a committed ``resolved`` item** — the
    exact state the earlier seeded first-pass test (an ``unresolved`` row) never
    exercised. The scoped-re-estimate gate must **not** match it: a first-pass event
    owns no item-scoped clarification question on an unresolved component, so it
    contributes nothing to ``intake`` / ``has_intake`` / ``uncounted_entries`` and
    surfaces no item on ``/log-events/by-date`` — nothing counts early. A realistic
    leftover ``unresolved`` component (no question) must not fake a re-estimate either.
    """

    upgrade(pg_engine, "head")
    user_id = _seed_pg_user(pg_engine)
    day = date(2026, 7, 10)
    factory = create_session_factory(pg_engine)

    with factory() as session:
        first_pass = LogEvent(
            user_id=user_id,
            raw_text="oatmeal and a mystery topping",
            status=LogEventStatus.PROCESSING,
            created_at=datetime(2026, 7, 10, 8, 0, tzinfo=UTC),
        )
        session.add(first_pass)
        session.flush()
        session.add_all(
            [
                DerivedFoodItem(
                    log_event_id=first_pass.id,
                    user_id=user_id,
                    name="oatmeal",
                    quantity_text="1 cup",
                    amount=1.0,
                    status=DerivedItemStatus.RESOLVED,
                    grams=234.0,
                    calories=150.0,
                    protein_g=5.0,
                    carbs_g=27.0,
                    fat_g=3.0,
                    calories_estimated=150.0,
                    protein_g_estimated=5.0,
                    carbs_g_estimated=27.0,
                    fat_g_estimated=3.0,
                ),
                DerivedFoodItem(
                    log_event_id=first_pass.id,
                    user_id=user_id,
                    name="mystery topping",
                    quantity_text="",
                    status=DerivedItemStatus.UNRESOLVED,
                ),
            ]
        )
        session.commit()
        first_pass_id = first_pass.id

    with factory() as session:
        loaded_user = session.get(User, user_id)
        assert loaded_user is not None
        single = daily_summary_service.get_daily_summary(session, user_id, loaded_user, day)
        ranged = daily_summary_service.get_daily_summaries(session, user_id, loaded_user, day, day)
        entries = log_event_service.list_entries_for_day(session, user_id, loaded_user, day)

    # Nothing counts early: the committed 150 kcal resolved row stays out of every
    # surface while the event is still ``processing`` mid-completion.
    assert ranged == [single]
    assert single.intake.calories == 0.0
    assert single.has_intake is False
    assert single.uncounted_entries == 0
    # The by-date read surfaces the event envelope but no item detail.
    first_pass_entries = [entry for entry in entries if entry.event.id == first_pass_id]
    assert len(first_pass_entries) == 1
    assert first_pass_entries[0].items == []


def test_uncounted_entries_holds_at_one_component_across_fresh_round_on_postgres(
    pg_engine: Engine,
) -> None:
    """FTY-349 Postgres parity: a fresh clarification round does not bump the count.

    ``uncounted_entries`` is one per still-``unresolved`` **component**, not per
    question row. When an answer-triggered re-estimate returns a fresh question on
    the same still-open component, the answered prior row is retained alongside the
    new open row, so two question rows link to one unresolved component. The count
    is taken over **distinct** components, so it stays ``1`` across the round and
    drops to ``0`` only when the component actually resolves — never the ``1 → 2``
    bump the per-row count produced.
    """

    upgrade(pg_engine, "head")
    user_id = _seed_pg_user(pg_engine)
    event_id, _resolved_id, unresolved_id = _seed_partial_event(pg_engine, str(user_id))
    day = date(2026, 7, 10)
    factory = create_session_factory(pg_engine)

    def _uncounted() -> int:
        with factory() as session:
            loaded_user = session.get(User, user_id)
            assert loaded_user is not None
            single = daily_summary_service.get_daily_summary(session, user_id, loaded_user, day)
            ranged = daily_summary_service.get_daily_summaries(
                session, user_id, loaded_user, day, day
            )
            assert ranged == [single]
            return single.uncounted_entries

    # One open question on the unresolved component → one uncounted entry.
    assert _uncounted() == 1

    # Answer it (retains the answered row, flips the event to ``processing``) and
    # land a fresh round: a second open question on the SAME still-unresolved
    # component.
    with factory() as session:
        loaded_user = session.get(User, user_id)
        assert loaded_user is not None
        questions = log_event_service.list_clarification_questions(
            session, user_id, loaded_user, event_id
        )
        clarification_service.answer_clarification_question(
            session, user_id, loaded_user, event_id, questions[0].id, "1 cup"
        )
    _add_followup_question(pg_engine, event_id, user_id, unresolved_id)

    # Two question rows now link to the one still-unresolved component…
    with factory() as session:
        rows = list(
            session.scalars(
                select(ClarificationQuestion).where(ClarificationQuestion.log_event_id == event_id)
            )
        )
        assert len(rows) == 2
        assert {row.derived_food_item_id for row in rows} == {unresolved_id}
    # …but the component is one uncounted entry — no ``1 → 2`` bump.
    assert _uncounted() == 1

    # It drops only when the component itself resolves.
    _resolve_open_component(pg_engine, event_id, unresolved_id)
    assert _uncounted() == 0


def test_partial_resolution_state_machine_and_counts_on_postgres(pg_engine: Engine) -> None:
    """Postgres parity for the seeded partial state, count, and answer idempotency."""

    upgrade(pg_engine, "head")
    factory = create_session_factory(pg_engine)
    user_id = _seed_pg_user(pg_engine)
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
