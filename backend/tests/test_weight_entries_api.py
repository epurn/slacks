"""Weight-entry API integration tests, including object-level authorization (FTY-070).

The cross-user negative tests are the security control this story must prove:
one user must not be able to create, list, or delete another user's weight
entries, and the API must fail closed as 404. The create + list-by-range
round-trip proves the canonical-kg contract end-to-end.

Weight values are sensitive personal data and are never logged.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

#: Exact NIST lb→kg factor — used to verify conversion in assertions.
_LB_TO_KG = 0.45359237


def _register(client: TestClient, email: str) -> tuple[str, str]:
    """Register a user, returning ``(user_id, auth_header_value)``."""

    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "a-good-password"},
    )
    assert resp.status_code == 201
    body = resp.json()
    return body["user"]["id"], f"Bearer {body['token']['access_token']}"


def _set_imperial(client: TestClient, user_id: str, auth: str) -> None:
    """Switch the user's units_preference to imperial."""

    resp = client.put(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": auth},
        json={"units_preference": "imperial"},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def test_create_metric_entry_stores_canonical_kg(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-metric@example.com")

    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 70.5, "effective_date": "2026-06-01"},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["user_id"] == user_id
    assert body["weight_kg"] == pytest.approx(70.5)
    assert body["effective_date"] == "2026-06-01"
    assert uuid.UUID(body["id"])


def test_create_imperial_entry_converts_to_kg(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-imperial@example.com")
    _set_imperial(client, user_id, auth)

    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 154.0, "effective_date": "2026-06-02"},
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["weight_kg"] == pytest.approx(154.0 * _LB_TO_KG, rel=1e-9)
    # The DTO always returns canonical kg, never the input lb value.
    assert body["weight_kg"] != 154.0


def test_create_returns_typed_dto_with_timestamps(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-dto@example.com")

    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 65.0, "effective_date": "2026-05-15"},
    )

    body = resp.json()
    assert "id" in body
    assert "created_at" in body
    assert "updated_at" in body


# ---------------------------------------------------------------------------
# List-by-range
# ---------------------------------------------------------------------------


def test_list_by_range_returns_only_entries_in_window(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-range@example.com")
    for day, weight in [("2026-05-01", 71.0), ("2026-06-01", 70.5), ("2026-07-01", 70.0)]:
        client.post(
            f"/api/users/{user_id}/weight-entries",
            headers={"Authorization": auth},
            json={"weight": weight, "effective_date": day},
        )

    resp = client.get(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        params={"from": "2026-05-15", "to": "2026-06-30"},
    )

    assert resp.status_code == 200
    dates = [e["effective_date"] for e in resp.json()]
    assert dates == ["2026-06-01"]


def test_list_by_range_ordered_oldest_first(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-order@example.com")
    for day in ["2026-06-10", "2026-06-01", "2026-06-05"]:
        client.post(
            f"/api/users/{user_id}/weight-entries",
            headers={"Authorization": auth},
            json={"weight": 70.0, "effective_date": day},
        )

    resp = client.get(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
    )

    assert resp.status_code == 200
    dates = [e["effective_date"] for e in resp.json()]
    assert dates == ["2026-06-01", "2026-06-05", "2026-06-10"]


def test_create_and_list_round_trip_returns_canonical_kg(client: TestClient) -> None:
    """A create + list-by-range round-trip must return the written entry in canonical kg."""

    user_id, auth = _register(client, "weight-roundtrip@example.com")
    _set_imperial(client, user_id, auth)

    post_resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 200.0, "effective_date": "2026-06-15"},
    )
    assert post_resp.status_code == 201
    expected_kg = 200.0 * _LB_TO_KG

    list_resp = client.get(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        params={"from": "2026-06-15", "to": "2026-06-15"},
    )
    assert list_resp.status_code == 200
    entries = list_resp.json()
    assert len(entries) == 1
    assert entries[0]["weight_kg"] == pytest.approx(expected_kg, rel=1e-9)
    assert entries[0]["id"] == post_resp.json()["id"]


def test_list_returns_empty_array_when_no_entries_in_range(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-empty@example.com")

    resp = client.get(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        params={"from": "2026-01-01", "to": "2026-01-31"},
    )

    assert resp.status_code == 200
    assert resp.json() == []


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def test_delete_removes_entry(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-delete@example.com")
    entry_id = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 70.0, "effective_date": "2026-06-01"},
    ).json()["id"]

    del_resp = client.delete(
        f"/api/users/{user_id}/weight-entries/{entry_id}",
        headers={"Authorization": auth},
    )
    assert del_resp.status_code == 204

    list_resp = client.get(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
    )
    assert list_resp.json() == []


def test_delete_unknown_entry_returns_404(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-del-unknown@example.com")

    resp = client.delete(
        f"/api/users/{user_id}/weight-entries/{uuid.uuid4()}",
        headers={"Authorization": auth},
    )

    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_create_rejects_zero_weight(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-zero@example.com")

    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 0.0, "effective_date": "2026-06-01"},
    )

    assert resp.status_code == 422


def test_create_rejects_negative_weight(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-negative@example.com")

    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": -10.0, "effective_date": "2026-06-01"},
    )

    assert resp.status_code == 422


def test_create_rejects_weight_above_1000kg_after_conversion(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-over1000@example.com")

    # 1000.001 kg > 1000 kg limit.
    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 1000.001, "effective_date": "2026-06-01"},
    )

    assert resp.status_code == 422


def test_create_accepts_weight_at_exactly_1000kg(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-1000kg@example.com")

    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 1000.0, "effective_date": "2026-06-01"},
    )

    assert resp.status_code == 201
    assert resp.json()["weight_kg"] == pytest.approx(1000.0)


def test_create_rejects_malformed_effective_date(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-baddate@example.com")

    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 70.0, "effective_date": "not-a-date"},
    )

    assert resp.status_code == 422


def test_create_rejects_unknown_body_key(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-extrakey@example.com")

    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 70.0, "effective_date": "2026-06-01", "note": "surprise"},
    )

    assert resp.status_code == 422


def test_list_rejects_inverted_range(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-inverted@example.com")

    resp = client.get(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        params={"from": "2026-06-30", "to": "2026-06-01"},
    )

    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


def test_endpoints_require_authentication(client: TestClient) -> None:
    user_id, _auth = _register(client, "weight-noauth@example.com")

    missing_create = client.post(
        f"/api/users/{user_id}/weight-entries",
        json={"weight": 70.0, "effective_date": "2026-06-01"},
    )
    missing_list = client.get(f"/api/users/{user_id}/weight-entries")
    bad_token = client.get(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert missing_create.status_code == 401
    assert missing_list.status_code == 401
    assert bad_token.status_code == 401


# ---------------------------------------------------------------------------
# Cross-user authorization (security: fail closed as 404)
# ---------------------------------------------------------------------------


def test_cross_user_create_fails_closed(client: TestClient) -> None:
    _alice_id, alice_auth = _register(client, "alice-weight-create@example.com")
    bob_id, bob_auth = _register(client, "bob-weight-create@example.com")

    # Alice presents a valid token but targets Bob's account.
    resp = client.post(
        f"/api/users/{bob_id}/weight-entries",
        headers={"Authorization": alice_auth},
        json={"weight": 80.0, "effective_date": "2026-06-01"},
    )

    assert resp.status_code == 404
    # Bob has no entries created on his behalf.
    bob_list = client.get(
        f"/api/users/{bob_id}/weight-entries", headers={"Authorization": bob_auth}
    )
    assert bob_list.json() == []


def test_cross_user_list_fails_closed(client: TestClient) -> None:
    alice_id, alice_auth = _register(client, "alice-weight-list@example.com")
    bob_id, bob_auth = _register(client, "bob-weight-list@example.com")
    client.post(
        f"/api/users/{bob_id}/weight-entries",
        headers={"Authorization": bob_auth},
        json={"weight": 75.0, "effective_date": "2026-06-01"},
    )

    resp = client.get(f"/api/users/{bob_id}/weight-entries", headers={"Authorization": alice_auth})

    assert resp.status_code == 404
    # Each owner can still read their own data.
    assert (
        client.get(
            f"/api/users/{alice_id}/weight-entries", headers={"Authorization": alice_auth}
        ).status_code
        == 200
    )


def test_cross_user_delete_fails_closed(client: TestClient) -> None:
    _alice_id, alice_auth = _register(client, "alice-weight-delete@example.com")
    bob_id, bob_auth = _register(client, "bob-weight-delete@example.com")
    bob_entry_id = client.post(
        f"/api/users/{bob_id}/weight-entries",
        headers={"Authorization": bob_auth},
        json={"weight": 80.0, "effective_date": "2026-06-01"},
    ).json()["id"]

    # Alice targeting Bob's delete path.
    resp = client.delete(
        f"/api/users/{bob_id}/weight-entries/{bob_entry_id}",
        headers={"Authorization": alice_auth},
    )

    assert resp.status_code == 404
    # Bob's entry must still exist.
    bob_list = client.get(
        f"/api/users/{bob_id}/weight-entries", headers={"Authorization": bob_auth}
    )
    assert len(bob_list.json()) == 1


def test_cross_user_entry_id_on_own_path_fails_closed(client: TestClient) -> None:
    """A cross-user entry_id under the caller's own path is also a 404."""

    alice_id, alice_auth = _register(client, "alice-weight-xid@example.com")
    bob_id, bob_auth = _register(client, "bob-weight-xid@example.com")
    bob_entry_id = client.post(
        f"/api/users/{bob_id}/weight-entries",
        headers={"Authorization": bob_auth},
        json={"weight": 80.0, "effective_date": "2026-06-01"},
    ).json()["id"]

    # Alice uses Bob's entry_id against her own user path.
    resp = client.delete(
        f"/api/users/{alice_id}/weight-entries/{bob_entry_id}",
        headers={"Authorization": alice_auth},
    )

    assert resp.status_code == 404


def _set_timezone(client: TestClient, user_id: str, auth: str, tz: str) -> None:
    """Update the user's profile timezone."""

    resp = client.put(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": auth},
        json={"timezone": tz},
    )
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Date-bound validation (FTY-119)
# ---------------------------------------------------------------------------


def test_create_rejects_far_future_date(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-future@example.com")

    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 70.0, "effective_date": "9999-01-01"},
    )

    assert resp.status_code == 422


def test_create_rejects_date_before_floor(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-pastfloor@example.com")

    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 70.0, "effective_date": "1800-01-01"},
    )

    assert resp.status_code == 422


def test_create_accepts_today_utc(client: TestClient) -> None:
    """The local machine date is offset-robust here: for a timezone-less user the
    endpoint accepts up to UTC-today + 1 day slack, and the local calendar date
    can never differ from the UTC calendar date by more than one day in either
    direction, so it always falls inside the accepted window.
    """

    user_id, auth = _register(client, "weight-today@example.com")
    today = date.today().isoformat()

    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 70.0, "effective_date": today},
    )

    assert resp.status_code == 201


def test_create_accepts_recent_past_date(client: TestClient) -> None:
    user_id, auth = _register(client, "weight-recentpast@example.com")

    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 70.0, "effective_date": "2025-01-15"},
    )

    assert resp.status_code == 201


def test_create_rejects_future_date_no_row_written(client: TestClient) -> None:
    """A rejected future date must write no row."""

    user_id, auth = _register(client, "weight-futurenorow@example.com")

    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 70.0, "effective_date": "9999-12-31"},
    )
    assert resp.status_code == 422

    list_resp = client.get(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
    )
    assert list_resp.json() == []


def test_create_timezone_boundary_ahead_of_utc(client: TestClient) -> None:
    """A date that is 'today' in a timezone ahead of UTC must be accepted.

    Pacific/Auckland is UTC+12 (or UTC+13 during NZDT). When the server's UTC
    date is D, the user's local date in Auckland is already D+1. An entry for
    D+1 (local today) must be accepted — not spuriously rejected by a UTC-based
    bound — because the slack accommodates this clock/tz skew.
    """

    user_id, auth = _register(client, "weight-tzahead@example.com")
    # Set the user's timezone well ahead of UTC so their "local today" may be UTC "tomorrow".
    _set_timezone(client, user_id, auth, "Pacific/Auckland")

    # Computed from actual UTC today, not the test-runner's local date: the
    # runner's local calendar date can itself be a day ahead of UTC, which
    # would silently push this past the +1 day slack and flake independently
    # of the Auckland boundary this test means to exercise.
    tomorrow_utc = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()

    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 70.0, "effective_date": tomorrow_utc},
    )

    assert resp.status_code == 201


def test_create_rejects_day_beyond_slack(client: TestClient) -> None:
    """A date two days beyond today (UTC) must be rejected even with the slack.

    Computed from UTC today, not the test-runner's local date: this user has no
    profile timezone, so the endpoint resolves "today" in UTC. Using the local
    date would make this test's pass/fail depend on the runner's clock and
    timezone offset relative to UTC.
    """

    user_id, auth = _register(client, "weight-beyond-slack@example.com")
    two_days_ahead = (datetime.now(UTC).date() + timedelta(days=2)).isoformat()

    resp = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers={"Authorization": auth},
        json={"weight": 70.0, "effective_date": two_days_ahead},
    )

    assert resp.status_code == 422
