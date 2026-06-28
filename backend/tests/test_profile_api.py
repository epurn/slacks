"""Profile API integration tests, including object-level authorization.

The negative authorization test is the security control this story must prove:
one user must not be able to read or write another user's profile, and the API
must fail closed.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


def _register(client: TestClient, email: str) -> tuple[str, str]:
    """Register a user, returning ``(user_id, auth_header_value)``."""

    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "a-good-password"},
    )
    assert resp.status_code == 201
    body = resp.json()
    return body["user"]["id"], f"Bearer {body['token']['access_token']}"


def test_profile_defaults_after_registration(client: TestClient) -> None:
    user_id, auth = _register(client, "owner@example.com")

    resp = client.get(f"/api/users/{user_id}/profile", headers={"Authorization": auth})

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == user_id
    assert body["height_m"] is None
    assert body["weight_kg"] is None
    assert body["metabolic_formula"] == "mifflin_st_jeor"
    assert body["units_preference"] == "metric"
    assert body["timezone"] == "UTC"


def test_profile_update_persists_canonical_units(client: TestClient) -> None:
    user_id, auth = _register(client, "owner2@example.com")

    resp = client.put(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": auth},
        json={
            "height_m": 1.75,
            "weight_kg": 70.5,
            "birth_year": 1990,
            "units_preference": "imperial",
            "timezone": "America/New_York",
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["height_m"] == 1.75
    assert body["weight_kg"] == 70.5
    assert body["birth_year"] == 1990
    # Display preference is captured but storage stays canonical (metres/kg).
    assert body["units_preference"] == "imperial"
    assert body["timezone"] == "America/New_York"

    # The update is persisted across requests.
    again = client.get(f"/api/users/{user_id}/profile", headers={"Authorization": auth})
    assert again.json()["weight_kg"] == 70.5


def test_profile_accepts_metabolic_formula_variants(client: TestClient) -> None:
    user_id, auth = _register(client, "formula@example.com")

    for variant in ("mifflin_st_jeor_plus5", "mifflin_st_jeor_minus161"):
        resp = client.put(
            f"/api/users/{user_id}/profile",
            headers={"Authorization": auth},
            json={"metabolic_formula": variant},
        )
        assert resp.status_code == 200, variant
        assert resp.json()["metabolic_formula"] == variant

    # The variant persists across requests.
    again = client.get(f"/api/users/{user_id}/profile", headers={"Authorization": auth})
    assert again.json()["metabolic_formula"] == "mifflin_st_jeor_minus161"


def test_profile_rejects_unknown_metabolic_formula(client: TestClient) -> None:
    user_id, auth = _register(client, "badformula@example.com")

    resp = client.put(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": auth},
        json={"metabolic_formula": "harris_benedict"},
    )

    assert resp.status_code == 422


def test_profile_partial_update_preserves_other_fields(client: TestClient) -> None:
    user_id, auth = _register(client, "owner3@example.com")
    client.put(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": auth},
        json={"height_m": 1.80, "weight_kg": 80.0},
    )

    resp = client.put(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": auth},
        json={"weight_kg": 78.0},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["weight_kg"] == 78.0
    assert body["height_m"] == 1.80  # untouched field preserved


def test_profile_rejects_invalid_input(client: TestClient) -> None:
    user_id, auth = _register(client, "owner4@example.com")

    negative_height = client.put(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": auth},
        json={"height_m": -1.0},
    )
    bad_timezone = client.put(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": auth},
        json={"timezone": "Mars/Olympus_Mons"},
    )

    assert negative_height.status_code == 422
    assert bad_timezone.status_code == 422


def test_profile_requires_authentication(client: TestClient) -> None:
    user_id, _auth = _register(client, "owner5@example.com")

    missing = client.get(f"/api/users/{user_id}/profile")
    bad_token = client.get(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": "Bearer not-a-real-token"},
    )

    assert missing.status_code == 401
    assert bad_token.status_code == 401


def test_cross_user_read_fails_closed(client: TestClient) -> None:
    alice_id, alice_auth = _register(client, "alice@example.com")
    bob_id, bob_auth = _register(client, "bob@example.com")

    # Alice presents a valid token but asks for Bob's profile.
    resp = client.get(f"/api/users/{bob_id}/profile", headers={"Authorization": alice_auth})

    # Fail closed as 404 (no existence oracle), and never leak Bob's data.
    assert resp.status_code == 404
    # Sanity: each owner can still read their own profile.
    assert (
        client.get(
            f"/api/users/{alice_id}/profile", headers={"Authorization": alice_auth}
        ).status_code
        == 200
    )
    assert (
        client.get(f"/api/users/{bob_id}/profile", headers={"Authorization": bob_auth}).status_code
        == 200
    )


@pytest.mark.parametrize("field", ["timezone", "units_preference", "metabolic_formula"])
def test_profile_rejects_explicit_null_on_required_fields(client: TestClient, field: str) -> None:
    """An explicit JSON null on a NOT NULL profile field must return 422 with no write."""

    user_id, auth = _register(client, f"null_{field}@example.com")

    resp = client.put(
        f"/api/users/{user_id}/profile",
        headers={"Authorization": auth},
        json={field: None},
    )

    assert resp.status_code == 422

    # Stored defaults must be unchanged — no partial write occurred.
    profile = client.get(f"/api/users/{user_id}/profile", headers={"Authorization": auth}).json()
    assert profile["timezone"] == "UTC"
    assert profile["units_preference"] == "metric"
    assert profile["metabolic_formula"] == "mifflin_st_jeor"


def test_cross_user_write_fails_closed(client: TestClient) -> None:
    _alice_id, alice_auth = _register(client, "alice2@example.com")
    bob_id, bob_auth = _register(client, "bob2@example.com")

    resp = client.put(
        f"/api/users/{bob_id}/profile",
        headers={"Authorization": alice_auth},
        json={"weight_kg": 999.0},
    )

    assert resp.status_code == 404
    # Bob's profile must be unchanged by Alice's attempted write.
    bob_view = client.get(f"/api/users/{bob_id}/profile", headers={"Authorization": bob_auth})
    assert bob_view.json()["weight_kg"] is None
