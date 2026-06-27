"""Save + typeahead endpoint tests, including object-level authz (FTY-052).

Covers the save happy path (one saved food + one alias row), the typeahead happy
path (name and alias hits, normalized folding, non-fuzzy exclusion), input
validation and the error shape, authentication, and the cross-user fail-closed
control that is the security gate for this story: a non-owner save or search must
neither write nor read another user's foods, nor confirm they exist.
"""

from __future__ import annotations

import uuid
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.models.saved_foods import FoodAlias, SavedFood
from tests.corrections_helpers import register


def _nutrition(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "calories": 200.0,
        "protein_g": 4.0,
        "carbs_g": 44.0,
        "fat_g": 0.4,
        "serving_size": 1.0,
        "serving_unit": "serving",
    }
    base.update(overrides)
    return base


def _save(
    client: TestClient,
    user_id: str,
    auth: str,
    *,
    name: str = "white rice",
    phrase: str = "my usual rice",
    nutrition: dict[str, object] | None = None,
) -> httpx.Response:
    body = {"name": name, "phrase": phrase, "nutrition": nutrition or _nutrition()}
    return cast(
        httpx.Response,
        client.post(
            f"/api/users/{user_id}/saved-foods",
            headers={"Authorization": auth},
            json=body,
        ),
    )


def _search(client: TestClient, user_id: str, auth: str, query: str) -> httpx.Response:
    return cast(
        httpx.Response,
        client.get(
            f"/api/users/{user_id}/saved-foods",
            headers={"Authorization": auth},
            params={"q": query},
        ),
    )


# --- save ---------------------------------------------------------------------


def test_save_creates_saved_food_and_alias(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "save@example.com")

    resp = _save(client, user_id, auth, name="White Rice", phrase="my usual rice")

    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "White Rice"
    assert body["calories"] == 200.0
    assert body["serving_unit"] == "serving"
    assert body["source"] == "saved_from_correction"
    assert body["user_id"] == user_id

    factory = create_session_factory(db_engine)
    with factory() as session:
        saved = session.query(SavedFood).filter_by(user_id=uuid.UUID(user_id)).one()
        assert saved.name_normalized == "white rice"
        aliases = session.query(FoodAlias).filter_by(saved_food_id=saved.id).all()
        assert len(aliases) == 1
        assert aliases[0].alias == "my usual rice"
        assert aliases[0].alias_normalized == "my usual rice"


def test_save_accepts_null_macros(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "null-macros@example.com")

    resp = _save(
        client,
        user_id,
        auth,
        nutrition=_nutrition(protein_g=None, carbs_g=None, fat_g=None),
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["protein_g"] is None
    assert body["carbs_g"] is None


@pytest.mark.parametrize(
    "nutrition",
    [
        _nutrition(calories=-1),  # negative energy
        _nutrition(calories=10_000_000),  # above sanity bound
        _nutrition(serving_size=0),  # non-positive serving
        _nutrition(serving_unit="   "),  # whitespace-only unit
    ],
)
def test_save_rejects_malformed_nutrition(
    client: TestClient, db_engine: Engine, nutrition: dict[str, object]
) -> None:
    user_id, auth = register(client, f"bad-nutrition-{hash(str(nutrition))}@example.com")

    resp = _save(client, user_id, auth, nutrition=nutrition)

    assert resp.status_code == 422


def test_save_rejects_empty_name(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "empty-name@example.com")
    resp = _save(client, user_id, auth, name="   ")
    assert resp.status_code == 422


def test_save_rejects_oversized_phrase(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "long-phrase@example.com")
    resp = _save(client, user_id, auth, phrase="x" * 201)
    assert resp.status_code == 422


def test_save_rejects_extra_field(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "extra@example.com")
    body = {
        "name": "rice",
        "phrase": "rice",
        "nutrition": _nutrition(),
        "source": "spoofed",
    }
    resp = client.post(
        f"/api/users/{user_id}/saved-foods", headers={"Authorization": auth}, json=body
    )
    assert resp.status_code == 422


def test_save_requires_authentication(client: TestClient, db_engine: Engine) -> None:
    user_id, _auth = register(client, "noauth-save@example.com")
    resp = client.post(
        f"/api/users/{user_id}/saved-foods",
        json={"name": "rice", "phrase": "rice", "nutrition": _nutrition()},
    )
    assert resp.status_code == 401


def test_cross_user_save_fails_closed(client: TestClient, db_engine: Engine) -> None:
    alice_id, alice_auth = register(client, "alice-save@example.com")
    bob_id, _bob_auth = register(client, "bob-save@example.com")

    # Alice presents a valid token but targets Bob's collection.
    resp = _save(client, bob_id, alice_auth, name="sneaky")

    assert resp.status_code == 404

    # Nothing was written under either user.
    factory = create_session_factory(db_engine)
    with factory() as session:
        assert session.query(SavedFood).count() == 0
        assert session.query(FoodAlias).count() == 0
    # And Alice's own (correctly-targeted) save still works, isolating the failure.
    ok = _save(client, alice_id, alice_auth, name="legit")
    assert ok.status_code == 201


# --- search -------------------------------------------------------------------


def test_search_matches_name_and_alias(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "search@example.com")
    _save(client, user_id, auth, name="Chicken Breast", phrase="my protein")
    _save(client, user_id, auth, name="White Rice", phrase="dinner carbs")

    # Name prefix.
    by_name = _search(client, user_id, auth, "chick")
    assert by_name.status_code == 200
    body = by_name.json()
    assert body["limit"] == 20
    assert [item["name"] for item in body["items"]] == ["Chicken Breast"]
    # Stored nutrition rides along so the client re-applies it directly.
    assert body["items"][0]["calories"] == 200.0

    # Contains (not a prefix).
    by_contains = _search(client, user_id, auth, "breast")
    assert [item["name"] for item in by_contains.json()["items"]] == ["Chicken Breast"]

    # Alias hit returns the alias's saved food.
    by_alias = _search(client, user_id, auth, "carbs")
    assert [item["name"] for item in by_alias.json()["items"]] == ["White Rice"]


def test_search_folds_case_diacritics_and_whitespace(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "fold@example.com")
    _save(client, user_id, auth, name="Café Latte", phrase="  Iced   Coffee  ")

    assert _search(client, user_id, auth, "cafe").json()["items"]
    assert _search(client, user_id, auth, "CAFÉ").json()["items"]
    # Alias matched after whitespace collapsing.
    assert _search(client, user_id, auth, "iced coffee").json()["items"]


def test_search_excludes_near_but_non_matching(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "nonmatch@example.com")
    _save(client, user_id, auth, name="Chicken Breast", phrase="poultry dinner")

    # Typo, synonym of the name, and missing separator: all excluded (no fuzzy/semantic).
    assert _search(client, user_id, auth, "chickne").json()["items"] == []
    assert _search(client, user_id, auth, "chickenbreast").json()["items"] == []
    # "poultry" only matches the alias here, proving the alias path is real...
    assert _search(client, user_id, auth, "poultry").json()["items"]
    # ...while a true non-match returns nothing.
    assert _search(client, user_id, auth, "tofu").json()["items"] == []


def test_search_only_returns_callers_own_foods(client: TestClient, db_engine: Engine) -> None:
    alice_id, alice_auth = register(client, "alice-search@example.com")
    bob_id, bob_auth = register(client, "bob-search@example.com")
    _save(client, alice_id, alice_auth, name="Alice Rice", phrase="alice phrase")
    _save(client, bob_id, bob_auth, name="Bob Rice", phrase="bob phrase")

    # Alice searching her own collection for a term present in both names sees only hers.
    resp = _search(client, alice_id, alice_auth, "rice")
    assert [item["name"] for item in resp.json()["items"]] == ["Alice Rice"]


def test_cross_user_search_fails_closed(client: TestClient, db_engine: Engine) -> None:
    alice_id, alice_auth = register(client, "alice-xsearch@example.com")
    bob_id, bob_auth = register(client, "bob-xsearch@example.com")
    _save(client, bob_id, bob_auth, name="Bob Secret Food", phrase="secret")

    # Alice targets Bob's collection with a valid token: fail closed, no data leak.
    resp = _search(client, bob_id, alice_auth, "secret")
    assert resp.status_code == 404
    assert "Bob" not in resp.text


def test_search_requires_authentication(client: TestClient, db_engine: Engine) -> None:
    user_id, _auth = register(client, "noauth-search@example.com")
    resp = client.get(f"/api/users/{user_id}/saved-foods", params={"q": "rice"})
    assert resp.status_code == 401


def test_search_rejects_missing_or_empty_query(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "badquery@example.com")

    missing = client.get(f"/api/users/{user_id}/saved-foods", headers={"Authorization": auth})
    empty = _search(client, user_id, auth, "")
    oversized = _search(client, user_id, auth, "x" * 201)

    assert missing.status_code == 422
    assert empty.status_code == 422
    assert oversized.status_code == 422


def test_alias_and_query_text_not_logged(
    client: TestClient, db_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    user_id, auth = register(client, "no-log-saved@example.com")
    private_phrase = "my-very-private-phrase-9f3"
    private_query = "another-private-query-7b1"

    with caplog.at_level("DEBUG"):
        _save(client, user_id, auth, name="rice", phrase=private_phrase)
        _search(client, user_id, auth, private_query)

    # The test client's own ``httpx`` logger echoes the request URL (and hence the
    # query string); that is test infrastructure, not application logging. Assert
    # that none of *our* loggers emit the sensitive phrase or query text.
    application_logs = "\n".join(
        record.getMessage() for record in caplog.records if record.name != "httpx"
    )
    assert private_phrase not in application_logs
    assert private_query not in application_logs
