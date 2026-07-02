"""Owner-scoped clarification-question read tests (FTY-152, FTY-170/171).

The estimator persists a `needs_clarification` event's questions (FTY-042); this
read path exposes the **open** ones to the owning client so the mobile clarify
sheet (FTY-153) can show Fatty's real question with its stable id and quick-pick
options. The tests prove: ordered exposure of the `{id, text, options}` shape,
the status gate (only a `needs_clarification` event serves questions), the
answered-question exclusion, the empty (no-rows) case, fail-closed
cross-user/unknown access, the no-status-oracle property, and that the sensitive
question text never reaches the logs.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.enums import LogEventStatus
from app.models.derived import ClarificationAnswer, ClarificationQuestion
from app.models.log_events import LogEvent


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
    status: LogEventStatus = LogEventStatus.NEEDS_CLARIFICATION,
    questions: list[str | tuple[str, list[str]]] | None = None,
    raw_text: str = "had some peanut butter",
) -> tuple[str, list[str]]:
    """Insert an owned event (and optional clarification rows).

    Returns ``(event_id, question_ids)`` with question ids in ``position`` order.
    Questions are seeded with shuffled ``position`` values so the read's ordering
    is genuinely exercised, not coincidentally satisfied by insertion order.
    """

    factory = create_session_factory(db_engine)
    with factory() as session:
        event = LogEvent(user_id=uuid.UUID(user_id), raw_text=raw_text, status=status)
        session.add(event)
        session.flush()
        rows: list[ClarificationQuestion] = []
        if questions:
            # Insert out of position order; the read must sort by ``position``.
            for position in reversed(range(len(questions))):
                question = questions[position]
                if isinstance(question, tuple):
                    question_text, options = question
                else:
                    question_text, options = question, []
                row = ClarificationQuestion(
                    log_event_id=event.id,
                    user_id=uuid.UUID(user_id),
                    question_text=question_text,
                    options=options,
                    position=position,
                )
                session.add(row)
                rows.append(row)
        session.commit()
        ordered = sorted(rows, key=lambda row: row.position)
        return str(event.id), [str(row.id) for row in ordered]


def _seed_answer(db_engine: Engine, user_id: str, event_id: str, question_id: str) -> None:
    """Persist an answer for ``question_id`` (marks it resolved)."""

    factory = create_session_factory(db_engine)
    with factory() as session:
        session.add(
            ClarificationAnswer(
                question_id=uuid.UUID(question_id),
                log_event_id=uuid.UUID(event_id),
                user_id=uuid.UUID(user_id),
                answer_text="4",
            )
        )
        session.commit()


def test_returns_questions_ordered_by_position(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = _register(client, "clarify-ordered@example.com")
    event_id, question_ids = _seed_event(
        db_engine,
        user_id,
        questions=[
            ("How much peanut butter?", ["1 tsp", "1 tbsp", "2 tbsp"]),
            ("Smooth or crunchy?", ["Smooth", "Crunchy"]),
        ],
    )

    resp = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/clarification",
        headers={"Authorization": auth},
    )

    assert resp.status_code == 200
    # Each question carries its stable persisted id (the answer-submission key),
    # its text, and its quick-pick options.
    assert resp.json() == {
        "questions": [
            {
                "id": question_ids[0],
                "text": "How much peanut butter?",
                "options": ["1 tsp", "1 tbsp", "2 tbsp"],
            },
            {
                "id": question_ids[1],
                "text": "Smooth or crunchy?",
                "options": ["Smooth", "Crunchy"],
            },
        ]
    }


def test_event_with_no_rows_returns_empty(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = _register(client, "clarify-empty@example.com")
    event_id, _ = _seed_event(db_engine, user_id, status=LogEventStatus.COMPLETED, questions=None)

    resp = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/clarification",
        headers={"Authorization": auth},
    )

    assert resp.status_code == 200
    assert resp.json() == {"questions": []}


def test_status_gated_wrong_status_serves_no_questions(
    client: TestClient, db_engine: Engine
) -> None:
    """Persisted rows are not served once the event has left needs_clarification.

    This is the mid-round window (log-events.md v4): answering one of two
    questions drives the event to ``processing`` while the sibling row is still
    persisted and unanswered — serving it would hand the client a chip whose
    fresh answer could only 409.
    """

    user_id, auth = _register(client, "clarify-status-gate@example.com")
    event_id, _ = _seed_event(
        db_engine,
        user_id,
        status=LogEventStatus.PROCESSING,
        questions=["How many crackers?"],
    )

    resp = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/clarification",
        headers={"Authorization": auth},
    )

    assert resp.status_code == 200
    assert resp.json() == {"questions": []}


def test_answered_question_is_not_reserved(client: TestClient, db_engine: Engine) -> None:
    """An answered question is resolved: only the still-open siblings are served."""

    user_id, auth = _register(client, "clarify-answered@example.com")
    event_id, question_ids = _seed_event(
        db_engine,
        user_id,
        questions=["How much peanut butter?", "Smooth or crunchy?"],
    )
    _seed_answer(db_engine, user_id, event_id, question_ids[0])

    resp = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/clarification",
        headers={"Authorization": auth},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "questions": [{"id": question_ids[1], "text": "Smooth or crunchy?", "options": []}]
    }


def test_no_status_oracle(client: TestClient, db_engine: Engine) -> None:
    """A wrong-status event and a needs_clarification event with no rows look identical."""

    user_id, auth = _register(client, "clarify-no-oracle@example.com")
    completed_id, _ = _seed_event(
        db_engine, user_id, status=LogEventStatus.COMPLETED, questions=["How many?"]
    )
    needs_clarification_id, _ = _seed_event(
        db_engine, user_id, status=LogEventStatus.NEEDS_CLARIFICATION, questions=None
    )

    completed = client.get(
        f"/api/users/{user_id}/log-events/{completed_id}/clarification",
        headers={"Authorization": auth},
    )
    needs_clarification = client.get(
        f"/api/users/{user_id}/log-events/{needs_clarification_id}/clarification",
        headers={"Authorization": auth},
    )

    assert completed.status_code == needs_clarification.status_code == 200
    assert completed.json() == needs_clarification.json() == {"questions": []}


def test_unknown_event_is_not_found(client: TestClient) -> None:
    user_id, auth = _register(client, "clarify-unknown@example.com")

    resp = client.get(
        f"/api/users/{user_id}/log-events/{uuid.uuid4()}/clarification",
        headers={"Authorization": auth},
    )

    assert resp.status_code == 404


def test_cross_user_read_fails_closed(client: TestClient, db_engine: Engine) -> None:
    _alice_id, alice_auth = _register(client, "clarify-alice@example.com")
    bob_id, _bob_auth = _register(client, "clarify-bob@example.com")
    bob_event_id, _ = _seed_event(db_engine, bob_id, questions=["How much rice?"])

    # Alice cannot read Bob's clarification via Bob's path nor via her own path,
    # and neither confirms the event exists (no existence oracle).
    via_bob_path = client.get(
        f"/api/users/{bob_id}/log-events/{bob_event_id}/clarification",
        headers={"Authorization": alice_auth},
    )
    via_alice_path = client.get(
        f"/api/users/{_alice_id}/log-events/{bob_event_id}/clarification",
        headers={"Authorization": alice_auth},
    )

    assert via_bob_path.status_code == 404
    assert via_alice_path.status_code == 404


def test_requires_authentication(client: TestClient, db_engine: Engine) -> None:
    user_id, _auth = _register(client, "clarify-noauth@example.com")
    event_id, _ = _seed_event(db_engine, user_id, questions=["How much rice?"])

    missing = client.get(f"/api/users/{user_id}/log-events/{event_id}/clarification")
    bad_token = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/clarification",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert missing.status_code == 401
    assert bad_token.status_code == 401


def test_question_and_raw_text_absent_from_logs(
    client: TestClient, db_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    user_id, auth = _register(client, "clarify-nolog@example.com")
    question = "How much peanut butter did you have?"
    raw_text = "secret peanut butter confession"
    event_id, _ = _seed_event(db_engine, user_id, questions=[question], raw_text=raw_text)

    with caplog.at_level("DEBUG"):
        resp = client.get(
            f"/api/users/{user_id}/log-events/{event_id}/clarification",
            headers={"Authorization": auth},
        )

    assert resp.status_code == 200
    # The sensitive question text and raw text must never reach the logs.
    assert question not in caplog.text
    assert raw_text not in caplog.text
