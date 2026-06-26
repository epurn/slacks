"""Log-event API integration tests, including object-level authorization (FTY-030).

The cross-user negative tests are the security control this story must prove: one
user must not be able to create, list, or read another user's log events, and the
API must fail closed. The transition test proves the ``pending → completed`` path
is exercisable end-to-end before the estimator exists.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.enums import LogEventStatus
from app.models.identity import User
from app.models.log_events import LogEvent
from app.services import log_events as log_event_service


def _register(client: TestClient, email: str) -> tuple[str, str]:
    """Register a user, returning ``(user_id, auth_header_value)``."""

    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "a-good-password"},
    )
    assert resp.status_code == 201
    body = resp.json()
    return body["user"]["id"], f"Bearer {body['token']['access_token']}"


def test_create_returns_pending_event(client: TestClient) -> None:
    user_id, auth = _register(client, "logger@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "  two eggs and toast  "},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["user_id"] == user_id
    assert body["status"] == "pending"
    # Surrounding whitespace is trimmed before storage.
    assert body["raw_text"] == "two eggs and toast"
    assert uuid.UUID(body["id"])


def test_list_today_returns_only_requested_day(client: TestClient) -> None:
    user_id, auth = _register(client, "today@example.com")
    create = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "a banana"},
    )
    event_id = create.json()["id"]
    created_day = create.json()["created_at"][:10]

    today = client.get(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        params={"day": created_day},
    )
    other_day = client.get(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        params={"day": "1999-01-01"},
    )

    assert today.status_code == 200
    assert [e["id"] for e in today.json()] == [event_id]
    assert other_day.status_code == 200
    assert other_day.json() == []


def test_list_defaults_to_today(client: TestClient) -> None:
    user_id, auth = _register(client, "default-day@example.com")
    create = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "a coffee"},
    )

    resp = client.get(f"/api/users/{user_id}/log-events", headers={"Authorization": auth})

    assert resp.status_code == 200
    assert [e["id"] for e in resp.json()] == [create.json()["id"]]


def test_get_by_id_returns_owned_event(client: TestClient) -> None:
    user_id, auth = _register(client, "getbyid@example.com")
    event_id = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "grilled chicken salad"},
    ).json()["id"]

    resp = client.get(
        f"/api/users/{user_id}/log-events/{event_id}", headers={"Authorization": auth}
    )

    assert resp.status_code == 200
    assert resp.json()["id"] == event_id
    assert resp.json()["raw_text"] == "grilled chicken salad"


def test_get_unknown_id_is_not_found(client: TestClient) -> None:
    user_id, auth = _register(client, "unknown@example.com")

    resp = client.get(
        f"/api/users/{user_id}/log-events/{uuid.uuid4()}", headers={"Authorization": auth}
    )

    assert resp.status_code == 404


def test_create_rejects_empty_text(client: TestClient) -> None:
    user_id, auth = _register(client, "empty@example.com")

    blank = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": ""},
    )
    whitespace = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "   "},
    )

    assert blank.status_code == 422
    assert whitespace.status_code == 422


def test_create_rejects_oversized_text(client: TestClient) -> None:
    user_id, auth = _register(client, "oversized@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "x" * 2001},
    )

    assert resp.status_code == 422


def test_create_rejects_unknown_field(client: TestClient) -> None:
    user_id, auth = _register(client, "extra@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "an apple", "status": "completed"},
    )

    assert resp.status_code == 422


def test_endpoints_require_authentication(client: TestClient) -> None:
    user_id, _auth = _register(client, "noauth@example.com")

    missing_create = client.post(f"/api/users/{user_id}/log-events", json={"raw_text": "an apple"})
    missing_list = client.get(f"/api/users/{user_id}/log-events")
    bad_token = client.get(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert missing_create.status_code == 401
    assert missing_list.status_code == 401
    assert bad_token.status_code == 401


def test_cross_user_create_fails_closed(client: TestClient) -> None:
    _alice_id, alice_auth = _register(client, "alice-log@example.com")
    bob_id, bob_auth = _register(client, "bob-log@example.com")

    # Alice presents a valid token but targets Bob's account.
    resp = client.post(
        f"/api/users/{bob_id}/log-events",
        headers={"Authorization": alice_auth},
        json={"raw_text": "not my event"},
    )

    assert resp.status_code == 404
    # Bob has no events created on his behalf.
    bob_list = client.get(f"/api/users/{bob_id}/log-events", headers={"Authorization": bob_auth})
    assert bob_list.json() == []


def test_cross_user_list_fails_closed(client: TestClient) -> None:
    alice_id, alice_auth = _register(client, "alice-list@example.com")
    bob_id, bob_auth = _register(client, "bob-list@example.com")
    client.post(
        f"/api/users/{bob_id}/log-events",
        headers={"Authorization": bob_auth},
        json={"raw_text": "bob's private log"},
    )

    resp = client.get(f"/api/users/{bob_id}/log-events", headers={"Authorization": alice_auth})

    assert resp.status_code == 404
    # Sanity: each owner still reads their own list.
    assert (
        client.get(
            f"/api/users/{alice_id}/log-events", headers={"Authorization": alice_auth}
        ).status_code
        == 200
    )


def test_cross_user_get_by_id_fails_closed(client: TestClient) -> None:
    _alice_id, alice_auth = _register(client, "alice-get@example.com")
    bob_id, bob_auth = _register(client, "bob-get@example.com")
    bob_event_id = client.post(
        f"/api/users/{bob_id}/log-events",
        headers={"Authorization": bob_auth},
        json={"raw_text": "bob's private log"},
    ).json()["id"]

    # Alice cannot read Bob's event by id even via her own path, and the API
    # does not confirm the event exists under Bob's path either.
    via_bob_path = client.get(
        f"/api/users/{bob_id}/log-events/{bob_event_id}", headers={"Authorization": alice_auth}
    )
    via_alice_path = client.get(
        f"/api/users/{_alice_id}/log-events/{bob_event_id}",
        headers={"Authorization": alice_auth},
    )

    assert via_bob_path.status_code == 404
    assert via_alice_path.status_code == 404


def test_pending_to_completed_transition_end_to_end(client: TestClient, db_engine: Engine) -> None:
    """Exercise the pending → completed transition before the estimator exists."""

    user_id, auth = _register(client, "transition@example.com")
    event_id = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "a sandwich"},
    ).json()["id"]

    # Drive the transition through the service contract (the test/admin path),
    # sharing the same database the API reads from.
    factory = create_session_factory(db_engine)
    with factory() as session:
        user = session.get(User, uuid.UUID(user_id))
        assert user is not None
        event = log_event_service.get_event(session, user.id, user, uuid.UUID(event_id))
        log_event_service.transition_event(session, event, LogEventStatus.COMPLETED)

    resp = client.get(
        f"/api/users/{user_id}/log-events/{event_id}", headers={"Authorization": auth}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_raw_text_is_stored_verbatim_after_trim(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = _register(client, "verbatim@example.com")
    event_id = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "150g rice and dal"},
    ).json()["id"]

    factory = create_session_factory(db_engine)
    with factory() as session:
        event = session.get(LogEvent, uuid.UUID(event_id))
        assert event is not None
        assert event.raw_text == "150g rice and dal"
        assert event.status == LogEventStatus.PENDING
