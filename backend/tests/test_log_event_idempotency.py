"""Offline idempotent-submit tests for the log-event create path (FTY-096).

These prove the safe-to-retry submit contract the mobile offline outbox (FTY-104)
depends on: a keyed create returns ``201`` and enqueues one job; any replay of the
same ``(user_id, idempotency_key)`` returns ``200`` with the existing event, creates
no new row, and enqueues nothing. The key namespace is per-user, the create path is
race-safe on the unique index, and replay is first-write-wins on body mismatch.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import LogEventStatus
from app.models.identity import User
from app.models.log_events import LogEvent
from app.services import log_events as log_event_service
from tests.conftest import RecordingEnqueuer


def _register(client: TestClient, email: str) -> tuple[str, str]:
    resp = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert resp.status_code == 201
    body = resp.json()
    return body["user"]["id"], f"Bearer {body['token']['access_token']}"


def _events_with_key(engine: Engine, key: str) -> list[LogEvent]:
    factory = create_session_factory(engine)
    with factory() as session:
        return list(session.scalars(select(LogEvent).where(LogEvent.idempotency_key == key)).all())


def test_keyed_create_then_replay_dedups_to_one_event(
    client: TestClient, enqueuer: RecordingEnqueuer, db_engine: Engine
) -> None:
    user_id, auth = _register(client, "idem@example.com")
    body = {"raw_text": "two eggs and toast", "idempotency_key": "outbox-key-1"}

    first = client.post(
        f"/api/users/{user_id}/log-events", headers={"Authorization": auth}, json=body
    )
    replay = client.post(
        f"/api/users/{user_id}/log-events", headers={"Authorization": auth}, json=body
    )

    # First create → 201; replay → 200, same event id.
    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]

    # Exactly one row and exactly one enqueue total.
    assert len(_events_with_key(db_engine, "outbox-key-1")) == 1
    assert len(enqueuer.calls) == 1


def test_replay_reflects_current_status_and_drives_pending_chain(
    client: TestClient, db_engine: Engine
) -> None:
    """A keyed create lands ``pending`` and replays at its current status."""

    user_id, auth = _register(client, "status@example.com")
    body = {"raw_text": "a sandwich", "idempotency_key": "outbox-key-2"}

    created = client.post(
        f"/api/users/{user_id}/log-events", headers={"Authorization": auth}, json=body
    )
    assert created.status_code == 201
    assert created.json()["status"] == "pending"
    event_id = created.json()["id"]

    # Drive the unchanged pending → processing → completed chain via the service.
    factory = create_session_factory(db_engine)
    with factory() as session:
        user = session.get(User, uuid.UUID(user_id))
        assert user is not None
        event = log_event_service.get_event(session, user.id, user, uuid.UUID(event_id))
        log_event_service.transition_event(session, event, LogEventStatus.PROCESSING)
        log_event_service.transition_event(session, event, LogEventStatus.COMPLETED)

    # A retry that arrives after the event advanced returns the current status,
    # so the client reconciles rather than resetting it.
    replay = client.post(
        f"/api/users/{user_id}/log-events", headers={"Authorization": auth}, json=body
    )
    assert replay.status_code == 200
    assert replay.json()["id"] == event_id
    assert replay.json()["status"] == "completed"


def test_replay_is_first_write_wins_on_body_mismatch(
    client: TestClient, enqueuer: RecordingEnqueuer, db_engine: Engine
) -> None:
    user_id, auth = _register(client, "mismatch@example.com")
    headers = {"Authorization": auth}

    first = client.post(
        f"/api/users/{user_id}/log-events",
        headers=headers,
        json={"raw_text": "the original entry", "idempotency_key": "outbox-key-3"},
    )
    # Same key, different body: the stored event is authoritative; the divergent
    # body is ignored (documented behaviour, not an error).
    replay = client.post(
        f"/api/users/{user_id}/log-events",
        headers=headers,
        json={"raw_text": "a totally different entry", "idempotency_key": "outbox-key-3"},
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["raw_text"] == "the original entry"
    assert len(_events_with_key(db_engine, "outbox-key-3")) == 1
    assert len(enqueuer.calls) == 1


def test_same_key_two_users_yields_two_events(
    client: TestClient, enqueuer: RecordingEnqueuer, db_engine: Engine
) -> None:
    """The key namespace is per-user: the same string never crosses users."""

    alice_id, alice_auth = _register(client, "alice-idem@example.com")
    bob_id, bob_auth = _register(client, "bob-idem@example.com")

    alice = client.post(
        f"/api/users/{alice_id}/log-events",
        headers={"Authorization": alice_auth},
        json={"raw_text": "alice's lunch", "idempotency_key": "shared-key"},
    )
    bob = client.post(
        f"/api/users/{bob_id}/log-events",
        headers={"Authorization": bob_auth},
        json={"raw_text": "bob's lunch", "idempotency_key": "shared-key"},
    )

    assert alice.status_code == 201
    assert bob.status_code == 201
    assert alice.json()["id"] != bob.json()["id"]
    # Two distinct events share the key string; both creates enqueued.
    assert len(_events_with_key(db_engine, "shared-key")) == 2
    assert len(enqueuer.calls) == 2


def test_concurrent_same_key_loser_returns_existing_not_500(
    client: TestClient,
    enqueuer: RecordingEnqueuer,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulate a lost race: the pre-insert lookup misses, the insert collides on
    the unique index, and the loser re-reads and returns the existing event."""

    user_id, auth = _register(client, "race@example.com")
    headers = {"Authorization": auth}
    body = {"raw_text": "eggs", "idempotency_key": "race-key"}

    first = client.post(f"/api/users/{user_id}/log-events", headers=headers, json=body)
    assert first.status_code == 201
    assert len(enqueuer.calls) == 1

    # Force only the pre-insert lookup to miss, as a racing submit would whose
    # read ran before the sibling committed; the real re-read still resolves it.
    real_find = log_event_service._find_by_key
    state = {"calls": 0}

    def flaky_find(session: Session, owner_id: uuid.UUID, key: str) -> LogEvent | None:
        state["calls"] += 1
        if state["calls"] == 1:
            return None
        return real_find(session, owner_id, key)

    monkeypatch.setattr(log_event_service, "_find_by_key", flaky_find)

    loser = client.post(f"/api/users/{user_id}/log-events", headers=headers, json=body)

    # Converges to one event: 200 (not 500), same id, no duplicate, no re-enqueue.
    assert loser.status_code == 200
    assert loser.json()["id"] == first.json()["id"]
    assert len(_events_with_key(db_engine, "race-key")) == 1
    assert len(enqueuer.calls) == 1


def test_no_key_creates_are_always_distinct(
    client: TestClient, enqueuer: RecordingEnqueuer
) -> None:
    """Back-compat: omitting the key creates a fresh event every time."""

    user_id, auth = _register(client, "nokey@example.com")
    headers = {"Authorization": auth}

    first = client.post(
        f"/api/users/{user_id}/log-events", headers=headers, json={"raw_text": "an apple"}
    )
    second = client.post(
        f"/api/users/{user_id}/log-events", headers=headers, json={"raw_text": "an apple"}
    )

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert len(enqueuer.calls) == 2


def test_idempotency_key_is_not_echoed_in_dto(client: TestClient) -> None:
    user_id, auth = _register(client, "noecho@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "a coffee", "idempotency_key": "secret-token"},
    )

    assert resp.status_code == 201
    assert "idempotency_key" not in resp.json()


def test_oversized_key_is_rejected(client: TestClient, enqueuer: RecordingEnqueuer) -> None:
    user_id, auth = _register(client, "longkey@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "an apple", "idempotency_key": "x" * 201},
    )

    assert resp.status_code == 422
    assert enqueuer.calls == []


def test_empty_or_whitespace_key_is_rejected(client: TestClient) -> None:
    user_id, auth = _register(client, "emptykey@example.com")
    headers = {"Authorization": auth}

    empty = client.post(
        f"/api/users/{user_id}/log-events",
        headers=headers,
        json={"raw_text": "an apple", "idempotency_key": ""},
    )
    whitespace = client.post(
        f"/api/users/{user_id}/log-events",
        headers=headers,
        json={"raw_text": "an apple", "idempotency_key": "   "},
    )

    assert empty.status_code == 422
    assert whitespace.status_code == 422


def test_wrong_type_key_is_rejected(client: TestClient) -> None:
    user_id, auth = _register(client, "typekey@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "an apple", "idempotency_key": 12345},
    )

    assert resp.status_code == 422


def test_null_key_path_is_unchanged(client: TestClient, enqueuer: RecordingEnqueuer) -> None:
    """An explicit ``null`` key behaves exactly as omitting it."""

    user_id, auth = _register(client, "nullkey@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "an apple", "idempotency_key": None},
    )

    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"
    assert len(enqueuer.calls) == 1
