"""Edit-endpoint API tests, including object-level authorization (FTY-051).

Covers the happy path (direct override + servings rescale), input validation and
the error shape, authentication, and the cross-user fail-closed control that is the
security gate for this story: a non-owner edit must neither mutate state nor reveal
that the item exists.
"""

from __future__ import annotations

import uuid
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.models.corrections import Correction
from app.models.derived import DerivedExerciseItem, DerivedFoodItem
from tests.corrections_helpers import register, seed_exercise_item, seed_food_item


def _patch(
    client: TestClient,
    user_id: str,
    item_type: str,
    item_id: uuid.UUID,
    auth: str,
    body: dict[str, object],
) -> httpx.Response:
    response = client.patch(
        f"/api/users/{user_id}/derived-items/{item_type}/{item_id}",
        headers={"Authorization": auth},
        json=body,
    )
    return cast(httpx.Response, response)


def test_direct_food_edit_returns_current_and_estimated(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "edit-food@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=200.0)

    resp = _patch(client, user_id, "food", item_id, auth, {"field": "calories", "value": 180})

    assert resp.status_code == 200
    body = resp.json()
    assert body["item_type"] == "food"
    assert body["calories"] == 180.0
    # The estimator original is preserved and returned alongside the current value.
    assert body["calories_estimated"] == 200.0


def test_quantity_rescale_through_api(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "edit-qty@example.com")
    item_id = seed_food_item(
        db_engine, user_id, amount=2.0, calories=300.0, protein_g=10.0, carbs_g=40.0, fat_g=5.0
    )

    resp = _patch(client, user_id, "food", item_id, auth, {"field": "quantity", "value": 3})

    assert resp.status_code == 200
    body = resp.json()
    assert body["amount"] == 3.0
    assert body["calories"] == 450.0
    assert body["protein_g"] == 15.0

    factory = create_session_factory(db_engine)
    with factory() as session:
        rows = session.query(Correction).filter_by(derived_food_item_id=item_id).all()
        # quantity + four rescaled fields.
        assert {r.field for r in rows} == {"quantity", "calories", "protein_g", "carbs_g", "fat_g"}


def test_exercise_burn_edit(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "edit-exercise@example.com")
    item_id = seed_exercise_item(db_engine, user_id, active_calories=120.0)

    resp = _patch(
        client, user_id, "exercise", item_id, auth, {"field": "active_calories", "value": 150}
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["item_type"] == "exercise"
    assert body["active_calories"] == 150.0
    assert body["active_calories_estimated"] == 120.0


def test_unknown_field_returns_clear_error_shape(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "unknown-field@example.com")
    item_id = seed_food_item(db_engine, user_id)

    resp = _patch(client, user_id, "food", item_id, auth, {"field": "bogus", "value": 1})

    assert resp.status_code == 422
    assert resp.json()["detail"] == {"error": "unknown_field", "field": "bogus"}


def test_out_of_range_value_is_rejected(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "out-of-range@example.com")
    item_id = seed_food_item(db_engine, user_id)

    resp = _patch(
        client, user_id, "food", item_id, auth, {"field": "calories", "value": 10_000_000}
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "out_of_range"


def test_negative_value_is_rejected(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "negative@example.com")
    item_id = seed_food_item(db_engine, user_id)

    resp = _patch(client, user_id, "food", item_id, auth, {"field": "calories", "value": -5})

    # Non-negativity is enforced at the request boundary (pydantic → 422).
    assert resp.status_code == 422


def test_invalid_old_quantity_fails_closed(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "zero-qty@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=0.0)

    resp = _patch(client, user_id, "food", item_id, auth, {"field": "quantity", "value": 2})

    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "invalid_old_quantity"


def test_unknown_item_type_is_rejected(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "bad-type@example.com")

    resp = _patch(client, user_id, "snack", uuid.uuid4(), auth, {"field": "calories", "value": 1})

    assert resp.status_code == 422


def test_unknown_item_is_not_found(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "missing-item@example.com")

    resp = _patch(client, user_id, "food", uuid.uuid4(), auth, {"field": "calories", "value": 1})

    assert resp.status_code == 404


def test_extra_field_in_body_is_rejected(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "extra-body@example.com")
    item_id = seed_food_item(db_engine, user_id)

    resp = _patch(
        client, user_id, "food", item_id, auth, {"field": "calories", "value": 1, "source": "x"}
    )

    assert resp.status_code == 422


def test_edit_requires_authentication(client: TestClient, db_engine: Engine) -> None:
    user_id, _auth = register(client, "noauth-edit@example.com")
    item_id = seed_food_item(db_engine, user_id)

    missing = client.patch(
        f"/api/users/{user_id}/derived-items/food/{item_id}",
        json={"field": "calories", "value": 1},
    )
    bad_token = client.patch(
        f"/api/users/{user_id}/derived-items/food/{item_id}",
        headers={"Authorization": "Bearer not-a-real-token"},
        json={"field": "calories", "value": 1},
    )

    assert missing.status_code == 401
    assert bad_token.status_code == 401


def test_cross_user_edit_fails_closed(client: TestClient, db_engine: Engine) -> None:
    alice_id, alice_auth = register(client, "alice-edit@example.com")
    bob_id, _bob_auth = register(client, "bob-edit@example.com")
    bob_item = seed_food_item(db_engine, bob_id, calories=200.0)

    # Alice presents a valid token but targets Bob's item, via both her path and his.
    via_bob_path = _patch(
        client, bob_id, "food", bob_item, alice_auth, {"field": "calories", "value": 999}
    )
    via_alice_path = _patch(
        client, alice_id, "food", bob_item, alice_auth, {"field": "calories", "value": 999}
    )

    assert via_bob_path.status_code == 404
    assert via_alice_path.status_code == 404

    # No mutation and no correction row was written for Bob's item.
    factory = create_session_factory(db_engine)
    with factory() as session:
        item = session.get(DerivedFoodItem, bob_item)
        assert item is not None
        assert item.calories == 200.0
        assert session.query(Correction).filter_by(derived_food_item_id=bob_item).count() == 0


def test_old_new_values_not_in_logs(
    client: TestClient, db_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    user_id, auth = register(client, "no-log@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=200.0)

    with caplog.at_level("DEBUG"):
        _patch(client, user_id, "food", item_id, auth, {"field": "calories", "value": 173.5})

    # The sensitive old/new values must never be logged.
    assert "173.5" not in caplog.text
    assert "200.0" not in caplog.text


def test_exercise_item_unaffected_by_food_edit_helpers(
    client: TestClient, db_engine: Engine
) -> None:
    # Sanity: a food field is unknown for an exercise item and fails closed at 422.
    user_id, auth = register(client, "wrong-field@example.com")
    item_id = seed_exercise_item(db_engine, user_id)

    resp = _patch(client, user_id, "exercise", item_id, auth, {"field": "calories", "value": 1})

    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "unknown_field"
    factory = create_session_factory(db_engine)
    with factory() as session:
        assert session.get(DerivedExerciseItem, item_id) is not None
