"""Item rename — audited display-name edit (FTY-377).

Covers the dedicated rename mutation and its audit semantics:

- happy path (food + exercise): ``name`` overwritten in place, exactly one
  immutable text-valued ``name_edit`` correction row appended (``old_value_text``
  / ``new_value_text`` set, ``new_value`` NULL);
- provenance honesty: a rename never flips ``is_edited``; the derived
  ``is_renamed`` reads ``false`` before and ``true`` after; a later value
  override still flips ``is_edited`` independently;
- fail-closed boundary: cross-user, unknown-item, and voided-parent renames
  render ``404`` with no mutation and no audit row;
- input validation: an empty / whitespace-only / over-length name renders the
  content-free ``422`` without echoing the submitted value, and mutates nothing;
- immutability: the ORM guards reject ``UPDATE``/``DELETE`` of a ``name_edit``
  row; the name value never appears in logs;
- read paths: the daily-summary read shows the new name and ``is_renamed``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.enums import CorrectionSource, LogEventStatus
from app.models.corrections import Correction, CorrectionImmutableError
from app.models.derived import DerivedFoodItem
from app.models.log_events import LogEvent
from tests.corrections_helpers import register, seed_exercise_item, seed_food_item


def _rename(
    client: TestClient,
    user_id: str,
    item_type: str,
    item_id: uuid.UUID,
    auth: str,
    body: dict[str, object],
) -> httpx.Response:
    response = client.patch(
        f"/api/users/{user_id}/derived-items/{item_type}/{item_id}/name",
        headers={"Authorization": auth},
        json=body,
    )
    return cast(httpx.Response, response)


def _name_edit_rows(
    db_engine: Engine, item_id: uuid.UUID, *, exercise: bool = False
) -> list[Correction]:
    factory = create_session_factory(db_engine)
    with factory() as session:
        column = (
            Correction.derived_exercise_item_id if exercise else Correction.derived_food_item_id
        )
        return (
            session.query(Correction)
            .filter(column == item_id, Correction.source == CorrectionSource.NAME_EDIT)
            .all()
        )


def test_rename_food_updates_name_and_appends_one_name_edit_row(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "rename-food@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=200.0)

    resp = _rename(client, user_id, "food", item_id, auth, {"name": "jasmine rice"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "jasmine rice"
    assert body["is_renamed"] is True
    assert body["is_edited"] is False
    # The numbers are untouched — a rename never re-resolves or re-costs.
    assert body["calories"] == 200.0
    assert body["calories_estimated"] == 200.0

    rows = _name_edit_rows(db_engine, item_id)
    assert len(rows) == 1
    row = rows[0]
    assert row.field == "name"
    assert row.old_value_text == "white rice"
    assert row.new_value_text == "jasmine rice"
    assert row.new_value is None
    assert row.old_value is None

    factory = create_session_factory(db_engine)
    with factory() as session:
        item = session.get(DerivedFoodItem, item_id)
        assert item is not None
        assert item.name == "jasmine rice"


def test_rename_exercise_updates_name_and_appends_one_name_edit_row(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "rename-exercise@example.com")
    item_id = seed_exercise_item(db_engine, user_id, active_calories=120.0)

    resp = _rename(client, user_id, "exercise", item_id, auth, {"name": "trail run"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["item_type"] == "exercise"
    assert body["name"] == "trail run"
    assert body["is_renamed"] is True
    assert body["is_edited"] is False
    assert body["active_calories"] == 120.0

    rows = _name_edit_rows(db_engine, item_id, exercise=True)
    assert len(rows) == 1
    assert rows[0].old_value_text == "running"
    assert rows[0].new_value_text == "trail run"
    assert rows[0].new_value is None


def test_is_renamed_false_before_rename_and_independent_of_is_edited(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "rename-flags@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=200.0)

    # Before any rename: a value edit flips is_edited only.
    edit = client.patch(
        f"/api/users/{user_id}/derived-items/food/{item_id}",
        headers={"Authorization": auth},
        json={"field": "calories", "value": 180},
    )
    assert edit.status_code == 200
    assert edit.json()["is_edited"] is True
    assert edit.json()["is_renamed"] is False

    # A rename flips is_renamed and leaves is_edited exactly as it was.
    resp = _rename(client, user_id, "food", item_id, auth, {"name": "brown rice"})
    assert resp.status_code == 200
    assert resp.json()["is_renamed"] is True
    assert resp.json()["is_edited"] is True


def test_later_value_override_flips_is_edited_independently_of_rename(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "rename-then-edit@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=200.0)

    renamed = _rename(client, user_id, "food", item_id, auth, {"name": "basmati rice"})
    assert renamed.status_code == 200
    # A never-value-edited renamed item reads is_edited = false.
    assert renamed.json()["is_edited"] is False
    assert renamed.json()["is_renamed"] is True

    edit = client.patch(
        f"/api/users/{user_id}/derived-items/food/{item_id}",
        headers={"Authorization": auth},
        json={"field": "calories", "value": 150},
    )
    assert edit.status_code == 200
    assert edit.json()["is_edited"] is True
    assert edit.json()["is_renamed"] is True

    factory = create_session_factory(db_engine)
    with factory() as session:
        sources = {
            row.source
            for row in session.query(Correction).filter_by(derived_food_item_id=item_id).all()
        }
        assert sources == {CorrectionSource.NAME_EDIT, CorrectionSource.USER_EDIT}


def test_rename_to_identical_name_is_a_safe_no_op(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "rename-noop@example.com")
    item_id = seed_food_item(db_engine, user_id)

    resp = _rename(client, user_id, "food", item_id, auth, {"name": "white rice"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "white rice"
    # No churn row: the item was not renamed, so is_renamed stays false.
    assert body["is_renamed"] is False
    assert _name_edit_rows(db_engine, item_id) == []


def test_rename_strips_surrounding_whitespace(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "rename-strip@example.com")
    item_id = seed_food_item(db_engine, user_id)

    resp = _rename(client, user_id, "food", item_id, auth, {"name": "  fried rice  "})

    assert resp.status_code == 200
    assert resp.json()["name"] == "fried rice"
    rows = _name_edit_rows(db_engine, item_id)
    assert len(rows) == 1
    assert rows[0].new_value_text == "fried rice"


def test_cross_user_rename_fails_closed(client: TestClient, db_engine: Engine) -> None:
    alice_id, alice_auth = register(client, "alice-rename@example.com")
    bob_id, _bob_auth = register(client, "bob-rename@example.com")
    bob_item = seed_food_item(db_engine, bob_id)

    via_bob_path = _rename(client, bob_id, "food", bob_item, alice_auth, {"name": "hijacked"})
    via_alice_path = _rename(client, alice_id, "food", bob_item, alice_auth, {"name": "hijacked"})

    assert via_bob_path.status_code == 404
    assert via_alice_path.status_code == 404

    factory = create_session_factory(db_engine)
    with factory() as session:
        item = session.get(DerivedFoodItem, bob_item)
        assert item is not None
        assert item.name == "white rice"  # no mutation
    assert _name_edit_rows(db_engine, bob_item) == []


def test_unknown_item_rename_is_not_found(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "rename-missing@example.com")

    resp = _rename(client, user_id, "food", uuid.uuid4(), auth, {"name": "ghost"})

    assert resp.status_code == 404


def test_voided_parent_rename_is_404_with_no_mutation(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "rename-voided@example.com")
    item_id = seed_food_item(db_engine, user_id)

    factory = create_session_factory(db_engine)
    with factory() as session:
        item = session.get(DerivedFoodItem, item_id)
        assert item is not None
        event = session.get(LogEvent, item.log_event_id)
        assert event is not None
        event.voided_at = datetime.now(UTC)
        session.commit()

    resp = _rename(client, user_id, "food", item_id, auth, {"name": "renamed anyway"})

    assert resp.status_code == 404
    with factory() as session:
        item = session.get(DerivedFoodItem, item_id)
        assert item is not None
        assert item.name == "white rice"  # no mutation
    assert _name_edit_rows(db_engine, item_id) == []


@pytest.mark.parametrize(
    "bad_name",
    ["", "   ", "x" * 201],
    ids=["empty", "whitespace-only", "over-length"],
)
def test_invalid_name_is_rejected_without_echo_or_mutation(
    client: TestClient, db_engine: Engine, bad_name: str
) -> None:
    user_id, auth = register(client, f"rename-bad-{len(bad_name)}@example.com")
    item_id = seed_food_item(db_engine, user_id)

    resp = _rename(client, user_id, "food", item_id, auth, {"name": bad_name})

    assert resp.status_code == 422
    # Content-free error shape: the submitted name is never echoed back.
    assert resp.json() == {"detail": {"error": "invalid_request"}}
    if bad_name.strip():
        assert bad_name not in resp.text

    factory = create_session_factory(db_engine)
    with factory() as session:
        item = session.get(DerivedFoodItem, item_id)
        assert item is not None
        assert item.name == "white rice"  # no mutation
    assert _name_edit_rows(db_engine, item_id) == []


def test_extra_body_key_is_rejected_content_free(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "rename-extra@example.com")
    item_id = seed_food_item(db_engine, user_id)

    resp = _rename(client, user_id, "food", item_id, auth, {"name": "ok", "calories": 1})

    assert resp.status_code == 422
    assert resp.json() == {"detail": {"error": "invalid_request"}}


def test_rename_requires_authentication(client: TestClient, db_engine: Engine) -> None:
    user_id, _auth = register(client, "rename-noauth@example.com")
    item_id = seed_food_item(db_engine, user_id)

    missing = client.patch(
        f"/api/users/{user_id}/derived-items/food/{item_id}/name",
        json={"name": "nope"},
    )
    bad_token = client.patch(
        f"/api/users/{user_id}/derived-items/food/{item_id}/name",
        headers={"Authorization": "Bearer not-a-real-token"},
        json={"name": "nope"},
    )

    assert missing.status_code == 401
    assert bad_token.status_code == 401


def test_name_edit_row_is_immutable(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "rename-tamper@example.com")
    item_id = seed_food_item(db_engine, user_id)
    renamed = _rename(client, user_id, "food", item_id, auth, {"name": "sushi rice"})
    assert renamed.status_code == 200
    (row,) = _name_edit_rows(db_engine, item_id)

    factory = create_session_factory(db_engine)
    with factory() as session:
        correction = session.get(Correction, row.id)
        assert correction is not None
        correction.new_value_text = "tampered"
        with pytest.raises(CorrectionImmutableError):
            session.commit()

    with factory() as session:
        correction = session.get(Correction, row.id)
        assert correction is not None
        assert correction.new_value_text == "sushi rice"

    with factory() as session:
        correction = session.get(Correction, row.id)
        assert correction is not None
        session.delete(correction)
        with pytest.raises(CorrectionImmutableError):
            session.commit()

    with factory() as session:
        assert session.get(Correction, row.id) is not None


def test_name_values_never_appear_in_logs(
    client: TestClient, db_engine: Engine, caplog: pytest.LogCaptureFixture
) -> None:
    user_id, auth = register(client, "rename-nolog@example.com")
    item_id = seed_food_item(db_engine, user_id)

    with caplog.at_level("DEBUG"):
        _rename(client, user_id, "food", item_id, auth, {"name": "secret midnight snack"})
        _rename(client, user_id, "food", item_id, auth, {"name": "   "})  # rejected

    assert "secret midnight snack" not in caplog.text
    assert "white rice" not in caplog.text


def test_by_date_read_shows_new_name_and_is_renamed(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "rename-summary@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=200.0)
    renamed = _rename(client, user_id, "food", item_id, auth, {"name": "poke bowl"})
    assert renamed.status_code == 200

    # Finalize the seeded event so the day-listing read includes its items.
    factory = create_session_factory(db_engine)
    with factory() as session:
        item = session.get(DerivedFoodItem, item_id)
        assert item is not None
        event = session.get(LogEvent, item.log_event_id)
        assert event is not None
        event.status = LogEventStatus.COMPLETED
        session.commit()

    resp = client.get(
        f"/api/users/{user_id}/log-events/by-date",
        headers={"Authorization": auth},
        params={"day": str(datetime.now(UTC).date())},
    )

    assert resp.status_code == 200
    items = [item for entry in resp.json() for item in entry["items"]]
    (read_item,) = [i for i in items if i["id"] == str(item_id)]
    assert read_item["name"] == "poke bowl"
    assert read_item["is_renamed"] is True
    assert read_item["is_edited"] is False
