"""Consolidated fail-closed object-level authorization sweep (FTY-073).

One cross-cutting proof of the threat-model "Broken object-level authorization"
control across **every** user-owned API surface at once: profile, log events,
derived-item corrections, saved foods, daily summary, and weight entries. The
per-feature ``test_*_api.py`` suites each prove their own resource in depth; this
sweep consolidates them so a new user-owned endpoint that forgets the control is
caught by a single security gate.

For each surface it asserts the three negatives fail closed:

- **unauthenticated** → ``401`` (credentials checked before ownership);
- **cross-user** (another user's token on the owner's path) → ``404``;
- **missing resource** (owner's token, unknown id) → ``404``.

Cross-user and missing are deliberately indistinguishable (both ``404``), so the
API never reveals that another user's record exists.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from tests.corrections_helpers import register, seed_food_item


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": token}


# --- unauthenticated → 401 (no seeding needed) ---------------------------------


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/users/{uid}/profile"),
        ("PUT", "/api/users/{uid}/profile"),
        ("GET", "/api/users/{uid}/log-events"),
        ("POST", "/api/users/{uid}/log-events"),
        ("GET", "/api/users/{uid}/log-events/{rid}"),
        ("GET", "/api/users/{uid}/daily-summary"),
        ("GET", "/api/users/{uid}/saved-foods"),
        ("POST", "/api/users/{uid}/saved-foods"),
        ("GET", "/api/users/{uid}/weight-entries"),
        ("POST", "/api/users/{uid}/weight-entries"),
        ("DELETE", "/api/users/{uid}/weight-entries/{rid}"),
        ("PATCH", "/api/users/{uid}/derived-items/food/{rid}"),
    ],
)
def test_user_owned_endpoints_require_authentication(
    client: TestClient, method: str, path: str
) -> None:
    url = path.format(uid=uuid.uuid4(), rid=uuid.uuid4())
    # No Authorization header, and a bad token, both fail closed before ownership.
    no_header = client.request(method, url, params={"q": "rice"})
    bad_token = client.request(
        method, url, params={"q": "rice"}, headers=_auth("Bearer not-a-real-token")
    )
    assert no_header.status_code == 401
    assert bad_token.status_code == 401


# --- cross-user and missing → 404 ----------------------------------------------


def _seed_owner(client: TestClient, db_engine: Engine, email: str) -> dict[str, str]:
    """Register a user and create one of each by-id resource; return ids + auth."""

    user_id, auth = register(client, email)

    event = client.post(
        f"/api/users/{user_id}/log-events", headers=_auth(auth), json={"raw_text": "rice"}
    )
    assert event.status_code == 201

    weight = client.post(
        f"/api/users/{user_id}/weight-entries",
        headers=_auth(auth),
        json={"weight": 70.5, "effective_date": "2026-06-01"},
    )
    assert weight.status_code == 201

    saved = client.post(
        f"/api/users/{user_id}/saved-foods",
        headers=_auth(auth),
        json={
            "name": "white rice",
            "phrase": "my usual rice",
            "nutrition": {
                "calories": 200.0,
                "protein_g": 4.0,
                "carbs_g": 44.0,
                "fat_g": 0.4,
                "serving_size": 1.0,
                "serving_unit": "serving",
            },
        },
    )
    assert saved.status_code == 201

    food_item_id = seed_food_item(db_engine, user_id)

    return {
        "user_id": user_id,
        "auth": auth,
        "event_id": event.json()["id"],
        "weight_id": weight.json()["id"],
        "food_item_id": str(food_item_id),
    }


def _read_paths(owner: dict[str, str]) -> list[tuple[str, str, dict[str, str]]]:
    """(method, path, params) tuples that read/mutate an owner-scoped resource."""

    uid = owner["user_id"]
    return [
        ("GET", f"/api/users/{uid}/profile", {}),
        ("GET", f"/api/users/{uid}/log-events", {}),
        ("GET", f"/api/users/{uid}/log-events/{owner['event_id']}", {}),
        ("GET", f"/api/users/{uid}/daily-summary", {}),
        ("GET", f"/api/users/{uid}/saved-foods", {"q": "rice"}),
        ("GET", f"/api/users/{uid}/weight-entries", {}),
        ("DELETE", f"/api/users/{uid}/weight-entries/{owner['weight_id']}", {}),
    ]


def test_cross_user_access_fails_closed_as_404(client: TestClient, db_engine: Engine) -> None:
    owner = _seed_owner(client, db_engine, "authz-owner@example.com")
    _, attacker_auth = register(client, "authz-attacker@example.com")

    for method, path, params in _read_paths(owner):
        resp = client.request(method, path, params=params, headers=_auth(attacker_auth))
        assert resp.status_code == 404, f"{method} {path} leaked (status {resp.status_code})"

    # The cross-user mutating edit also fails closed (and must not mutate).
    patch = client.request(
        "PATCH",
        f"/api/users/{owner['user_id']}/derived-items/food/{owner['food_item_id']}",
        headers=_auth(attacker_auth),
        json={"field": "calories", "value": 999},
    )
    assert patch.status_code == 404


def test_missing_resource_is_indistinguishable_from_forbidden(
    client: TestClient, db_engine: Engine
) -> None:
    owner = _seed_owner(client, db_engine, "authz-missing@example.com")
    uid, auth = owner["user_id"], owner["auth"]
    unknown = uuid.uuid4()

    # Owner's own token, but an id that does not exist → 404 (same as cross-user).
    edit = {"field": "calories", "value": 1}
    cases = [
        ("GET", f"/api/users/{uid}/log-events/{unknown}", None),
        ("DELETE", f"/api/users/{uid}/weight-entries/{unknown}", None),
        ("PATCH", f"/api/users/{uid}/derived-items/food/{unknown}", edit),
    ]
    for method, path, body in cases:
        resp = client.request(method, path, headers=_auth(auth), json=body)
        assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}"
