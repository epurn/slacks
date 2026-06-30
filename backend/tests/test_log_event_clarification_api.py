"""Owner-scoped clarification-question read tests (FTY-152).

The estimator already produces and persists a `needs_clarification` event's
questions (FTY-042); this read path exposes them to the owning client so the
mobile clarify sheet (FTY-153) can show Fatty's real question. The tests prove:
ordered exposure, the empty (no-rows) case, fail-closed cross-user/unknown access,
the no-status-oracle property, and that the sensitive question text never reaches
the logs.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.enums import LogEventStatus
from app.models.derived import ClarificationQuestion
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
    questions: list[str] | None = None,
    raw_text: str = "had some peanut butter",
) -> str:
    """Insert an owned event (and optional clarification rows), returning its id.

    Questions are seeded with shuffled ``position`` values so the read's ordering
    is genuinely exercised, not coincidentally satisfied by insertion order.
    """

    factory = create_session_factory(db_engine)
    with factory() as session:
        event = LogEvent(user_id=uuid.UUID(user_id), raw_text=raw_text, status=status)
        session.add(event)
        session.flush()
        if questions:
            # Insert out of position order; the read must sort by ``position``.
            for position in reversed(range(len(questions))):
                session.add(
                    ClarificationQuestion(
                        log_event_id=event.id,
                        user_id=uuid.UUID(user_id),
                        question_text=questions[position],
                        position=position,
                    )
                )
        session.commit()
        return str(event.id)


def test_returns_questions_ordered_by_position(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = _register(client, "clarify-ordered@example.com")
    event_id = _seed_event(
        db_engine,
        user_id,
        questions=["How much peanut butter?", "Smooth or crunchy?"],
    )

    resp = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/clarification",
        headers={"Authorization": auth},
    )

    assert resp.status_code == 200
    assert resp.json() == {
        "questions": [
            {"text": "How much peanut butter?"},
            {"text": "Smooth or crunchy?"},
        ]
    }


def test_event_with_no_rows_returns_empty(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = _register(client, "clarify-empty@example.com")
    event_id = _seed_event(db_engine, user_id, status=LogEventStatus.COMPLETED, questions=None)

    resp = client.get(
        f"/api/users/{user_id}/log-events/{event_id}/clarification",
        headers={"Authorization": auth},
    )

    assert resp.status_code == 200
    assert resp.json() == {"questions": []}


def test_no_status_oracle(client: TestClient, db_engine: Engine) -> None:
    """A wrong-status event and a needs_clarification event with no rows look identical."""

    user_id, auth = _register(client, "clarify-no-oracle@example.com")
    completed_id = _seed_event(db_engine, user_id, status=LogEventStatus.COMPLETED)
    needs_clarification_id = _seed_event(
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
    bob_event_id = _seed_event(db_engine, bob_id, questions=["How much rice?"])

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
    event_id = _seed_event(db_engine, user_id, questions=["How much rice?"])

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
    event_id = _seed_event(db_engine, user_id, questions=[question], raw_text=raw_text)

    with caplog.at_level("DEBUG"):
        resp = client.get(
            f"/api/users/{user_id}/log-events/{event_id}/clarification",
            headers={"Authorization": auth},
        )

    assert resp.status_code == 200
    # The sensitive question text and raw text must never reach the logs.
    assert question not in caplog.text
    assert raw_text not in caplog.text
