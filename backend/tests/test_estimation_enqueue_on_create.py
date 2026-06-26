"""The FTY-030 create path enqueues an estimation job (FTY-040).

Proves the create → enqueue trigger without a live broker: the recording
enqueuer captures exactly one publish carrying the new event's id and owner, and
a failed create (cross-user) enqueues nothing.
"""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from tests.conftest import RecordingEnqueuer


def _register(client: TestClient, email: str) -> tuple[str, str]:
    resp = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert resp.status_code == 201
    body = resp.json()
    return body["user"]["id"], f"Bearer {body['token']['access_token']}"


def test_create_enqueues_one_job_with_ids(client: TestClient, enqueuer: RecordingEnqueuer) -> None:
    user_id, auth = _register(client, "enqueue@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "two eggs and toast"},
    )

    assert resp.status_code == 201
    event_id = uuid.UUID(resp.json()["id"])
    assert enqueuer.calls == [(event_id, uuid.UUID(user_id))]


def test_failed_cross_user_create_enqueues_nothing(
    client: TestClient, enqueuer: RecordingEnqueuer
) -> None:
    _alice_id, alice_auth = _register(client, "alice-enq@example.com")
    bob_id, _bob_auth = _register(client, "bob-enq@example.com")

    # Alice targets Bob's account: the create fails closed (404) and must not
    # publish a job.
    resp = client.post(
        f"/api/users/{bob_id}/log-events",
        headers={"Authorization": alice_auth},
        json={"raw_text": "not my event"},
    )

    assert resp.status_code == 404
    assert enqueuer.calls == []
