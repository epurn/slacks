"""Exact-evidence proposal apply — backend route tests (FTY-307).

The API-level endpoint coverage for ``POST .../exact-upgrade/apply``: authz,
request-boundary validation, sanitized fail-closed bodies, and the fail-closed
404 (cross-user / unknown / voided-parent) / 422 (proposal_not_resolvable /
amount_required / invalid_request) mapping. Split out of
``test_exact_evidence_apply.py`` (FTY-361); the proposal-model/service-level
tests stay there, and both files import the shared builders + ``session``
fixture from ``tests.exact_evidence_helpers``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import SourceType
from app.estimator.exact_evidence import encode_proposal_ref
from app.models.derived import DerivedFoodItem
from app.models.log_events import LogEvent
from app.schemas.exact_evidence import MAX_PROPOSAL_REF_LENGTH
from app.settings import DEV_AUTH_SECRET
from tests.corrections_helpers import register, seed_food_item
from tests.exact_evidence_helpers import (
    _apply_url,
    _exact_proposal,
    _fallback_proposal,
    _ref_for_app,
)
from tests.exact_evidence_helpers import session as session  # noqa: PLC0414 — re-exported fixture


def test_apply_api_fallback_claiming_high_trust_source_is_422_no_mutation(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    # End-to-end: a fallback signed with product_database renders the contracted
    # 422 proposal_not_resolvable with no mutation (never a masquerading exact apply).
    user_id, auth = register(client, "ee-api-fb-hitrust@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    ref = encode_proposal_ref(
        _fallback_proposal(
            uuid.UUID(user_id), item_id, source_type=SourceType.PRODUCT_DATABASE.value
        ),
        DEV_AUTH_SECRET,
    )

    resp = client.post(
        _apply_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"proposal_ref": ref},
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "proposal_not_resolvable"
    session.expire_all()
    assert session.get(DerivedFoodItem, item_id).calories == pytest.approx(300.0)  # type: ignore[union-attr]


def test_apply_api_happy_path(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "ee-api@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)

    resp = client.post(
        _apply_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"proposal_ref": _ref_for_app(user_id, item_id)},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["calories"] == pytest.approx(360.0)
    assert body["is_edited"] is False
    assert body["source"]["source_type"] == "product_database"
    assert body["source"]["ref"] == "open_food_facts:0123456789012"


def test_apply_api_rejects_client_supplied_facts(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "ee-api-inject@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=300.0)

    resp = client.post(
        _apply_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"proposal_ref": _ref_for_app(user_id, item_id), "calories": 50.0},
    )

    assert resp.status_code == 422  # extra=forbid: no fact injection
    assert resp.json() == {"detail": {"error": "invalid_request"}}  # sanitized: fact not echoed


def test_apply_api_unknown_reference_is_422(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "ee-api-badref@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=300.0)

    resp = client.post(
        _apply_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"proposal_ref": "not-a-real-ref"},
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "proposal_not_resolvable"


def test_apply_api_oversized_reference_is_422_no_mutation(
    client: TestClient, db_engine: Engine, session: Session
) -> None:
    # Oversized proposal_ref rejected at the request boundary (before HMAC/base64/JSON
    # decode) — 422, no mutation, sanitized stable-code body that never echoes the ref.
    user_id, auth = register(client, "ee-api-oversized@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=300.0)
    resp = client.post(
        _apply_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"proposal_ref": "a" * (MAX_PROPOSAL_REF_LENGTH + 1)},
    )

    assert resp.status_code == 422
    assert resp.json() == {"detail": {"error": "invalid_request"}}
    session.expire_all()
    assert session.get(DerivedFoodItem, item_id).calories == pytest.approx(300.0)  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("case", "malformed_ref"),
    [("payload", "é.c2ln"), ("signature", "cGF5.é"), ("both", "é.é")],
)
def test_apply_api_non_ascii_reference_is_422_no_mutation(
    client: TestClient, db_engine: Engine, session: Session, case: str, malformed_ref: str
) -> None:
    # A malformed non-ASCII proposal_ref must render the contracted 422
    # proposal_not_resolvable with no mutation — never a 500 from an unmapped
    # UnicodeError/TypeError in signature verification.
    user_id, auth = register(client, f"ee-api-nonascii-{case}@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=300.0)

    resp = client.post(
        _apply_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"proposal_ref": malformed_ref},
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "proposal_not_resolvable"
    session.expire_all()
    assert session.get(DerivedFoodItem, item_id).calories == pytest.approx(300.0)  # type: ignore[union-attr]


def test_apply_api_expired_reference_is_422(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "ee-api-expired@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=300.0)
    expired = encode_proposal_ref(
        _exact_proposal(uuid.UUID(user_id), item_id, now=datetime.now(UTC) - timedelta(days=1)),
        DEV_AUTH_SECRET,
    )

    resp = client.post(
        _apply_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"proposal_ref": expired},
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "proposal_not_resolvable"


def test_apply_api_uncostable_amount_is_422(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "ee-api-amount@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)

    resp = client.post(
        _apply_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"proposal_ref": _ref_for_app(user_id, item_id, default_serving_g=None)},
    )

    assert resp.status_code == 422
    assert resp.json()["detail"]["error"] == "amount_required"


def test_apply_api_negative_amount_is_422(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "ee-api-negamount@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)

    resp = client.post(
        _apply_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"proposal_ref": _ref_for_app(user_id, item_id), "amount": -1.0},
    )

    assert resp.status_code == 422  # request-boundary validation


def test_apply_api_unknown_item_is_404(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "ee-api-missing@example.com")
    missing = uuid.uuid4()

    resp = client.post(
        _apply_url(user_id, missing),
        headers={"Authorization": auth},
        json={"proposal_ref": _ref_for_app(user_id, missing)},
    )

    assert resp.status_code == 404


def test_apply_api_cross_user_fails_closed(client: TestClient, db_engine: Engine) -> None:
    alice_id, alice_auth = register(client, "ee-alice@example.com")
    bob_id, _bob_auth = register(client, "ee-bob@example.com")
    bob_item = seed_food_item(db_engine, bob_id, amount=2.0, calories=200.0)

    via_bob = client.post(
        _apply_url(bob_id, bob_item),
        headers={"Authorization": alice_auth},
        json={"proposal_ref": _ref_for_app(bob_id, bob_item)},
    )
    via_alice = client.post(
        _apply_url(alice_id, bob_item),
        headers={"Authorization": alice_auth},
        json={"proposal_ref": _ref_for_app(alice_id, bob_item)},
    )

    assert via_bob.status_code == 404
    assert via_alice.status_code == 404
    factory = create_session_factory(db_engine)
    with factory() as s:
        item = s.get(DerivedFoodItem, bob_item)
        assert item is not None
        assert item.calories == pytest.approx(200.0)  # no mutation


def test_apply_api_voided_parent_is_404(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "ee-api-voided@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)
    ref = _ref_for_app(user_id, item_id)
    # Void the item's parent log event (FTY-321 soft void).
    factory = create_session_factory(db_engine)
    with factory() as s:
        item = s.get(DerivedFoodItem, item_id)
        assert item is not None
        event = s.get(LogEvent, item.log_event_id)
        assert event is not None
        event.voided_at = datetime.now(UTC)
        s.commit()

    resp = client.post(
        _apply_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"proposal_ref": ref},
    )

    assert resp.status_code == 404
    with factory() as s:
        item = s.get(DerivedFoodItem, item_id)
        assert item is not None
        assert item.calories == pytest.approx(300.0)  # no mutation


def test_apply_api_requires_authentication(client: TestClient, db_engine: Engine) -> None:
    user_id, _auth = register(client, "ee-api-noauth@example.com")
    item_id = seed_food_item(db_engine, user_id)

    resp = client.post(
        _apply_url(user_id, item_id),
        json={"proposal_ref": _ref_for_app(user_id, item_id)},
    )

    assert resp.status_code == 401


def test_apply_api_then_edit_marks_item_edited_again(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "ee-api-then-edit@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=2.0, calories=300.0)

    applied = client.post(
        _apply_url(user_id, item_id),
        headers={"Authorization": auth},
        json={"proposal_ref": _ref_for_app(user_id, item_id)},
    )
    assert applied.status_code == 200
    assert applied.json()["is_edited"] is False

    edit = client.patch(
        f"/api/users/{user_id}/derived-items/food/{item_id}",
        headers={"Authorization": auth},
        json={"field": "calories", "value": 250.0},
    )
    assert edit.status_code == 200
    assert edit.json()["is_edited"] is True
