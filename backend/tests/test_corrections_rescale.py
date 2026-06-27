"""Deterministic rescale + snapshot unit tests for the corrections service (FTY-051).

Exercises the edit semantics directly through ``edit_derived_item`` against a
migrated SQLite database: exact worked ratio examples (including a fractional ratio
with rounding), the per-field correction rows, the zero/invalid old-quantity
fail-closed path, snapshot-once-never-mutate, and last-edit-wins.
"""

from __future__ import annotations

import uuid
from typing import cast

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.enums import CandidateType
from app.models.corrections import Correction
from app.models.derived import DerivedFoodItem
from app.models.identity import User
from app.services import corrections as svc
from tests.corrections_helpers import register, seed_food_item


def _edit(
    db_engine: Engine,
    user_id: str,
    item_type: CandidateType,
    item_id: uuid.UUID,
    field: str,
    value: float,
) -> tuple[DerivedFoodItem, list[Correction], list[Correction]]:
    """Run one edit through the service and return (refreshed item, returned, persisted)."""

    factory = create_session_factory(db_engine)
    with factory() as session:
        user = session.get(User, uuid.UUID(user_id))
        assert user is not None
        result = svc.edit_derived_item(
            session, uuid.UUID(user_id), user, item_type, item_id, field, value
        )
        # The service refreshed ``result.item`` post-commit, so it reflects the
        # persisted state; read the audit rows back alongside it.
        persisted = list(
            session.scalars(select(Correction).where(Correction.derived_food_item_id == item_id))
        )
        return cast(DerivedFoodItem, result.item), result.corrections, persisted


def test_quantity_rescale_applies_ratio_to_current_values(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, _ = register(client, "rescale@example.com")
    item_id = seed_food_item(
        db_engine,
        user_id,
        amount=2.0,
        calories=300.0,
        protein_g=10.0,
        carbs_g=40.0,
        fat_g=5.0,
    )

    item, returned, persisted = _edit(
        db_engine, user_id, CandidateType.FOOD, item_id, "quantity", 3.0
    )

    # ratio = 3 / 2 = 1.5 applied to the current values.
    assert item.amount == 3.0
    assert (item.calories, item.protein_g, item.carbs_g, item.fat_g) == (450.0, 15.0, 60.0, 7.5)
    # One correction for the quantity change plus one per rescaled field.
    by_field = {c.field: (c.old_value, c.new_value) for c in persisted}
    assert by_field == {
        "quantity": (2.0, 3.0),
        "calories": (300.0, 450.0),
        "protein_g": (10.0, 15.0),
        "carbs_g": (40.0, 60.0),
        "fat_g": (5.0, 7.5),
    }
    assert len(returned) == 5


def test_quantity_rescale_fractional_ratio_rounds_to_one_decimal(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, _ = register(client, "fractional@example.com")
    item_id = seed_food_item(
        db_engine, user_id, amount=3.0, calories=100.0, protein_g=10.0, carbs_g=10.0, fat_g=1.0
    )

    item, _returned, _persisted = _edit(
        db_engine, user_id, CandidateType.FOOD, item_id, "quantity", 1.0
    )

    # ratio = 1 / 3; 100/3 = 33.33… → 33.3, 10/3 = 3.33… → 3.3, 1/3 = 0.33… → 0.3.
    assert item.calories == 33.3
    assert item.protein_g == 3.3
    assert item.carbs_g == 3.3
    assert item.fat_g == 0.3


def test_quantity_rescale_preserves_estimated_snapshot(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, _ = register(client, "preserve@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=1.0, calories=200.0)

    item, _returned, _persisted = _edit(
        db_engine, user_id, CandidateType.FOOD, item_id, "quantity", 2.0
    )

    assert item.calories == 400.0
    # The original estimate is preserved immutably while the current value doubled.
    assert item.calories_estimated == 200.0


@pytest.mark.parametrize("old_quantity", [0.0, None])
def test_quantity_rescale_fails_closed_on_invalid_old_quantity(
    client: TestClient, db_engine: Engine, old_quantity: float | None
) -> None:
    user_id, _ = register(client, f"badq{old_quantity}@example.com")
    item_id = seed_food_item(db_engine, user_id, amount=old_quantity)

    factory = create_session_factory(db_engine)
    with factory() as session:
        user = session.get(User, uuid.UUID(user_id))
        assert user is not None
        with pytest.raises(svc.InvalidCorrection) as exc:
            svc.edit_derived_item(
                session, uuid.UUID(user_id), user, CandidateType.FOOD, item_id, "quantity", 2.0
            )
        assert exc.value.code == "invalid_old_quantity"

    # No correction row was written and the item is untouched.
    factory = create_session_factory(db_engine)
    with factory() as session:
        assert session.scalars(select(Correction)).all() == []
        item = session.get(DerivedFoodItem, item_id)
        assert item is not None
        assert item.calories == 200.0


def test_direct_edit_overrides_one_field_with_single_correction(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, _ = register(client, "direct@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=200.0)

    item, returned, persisted = _edit(
        db_engine, user_id, CandidateType.FOOD, item_id, "calories", 250.0
    )

    assert item.calories == 250.0
    # Other macros and the original snapshot are untouched.
    assert item.protein_g == 4.0
    assert item.calories_estimated == 200.0
    assert len(returned) == 1
    assert len(persisted) == 1
    assert (persisted[0].field, persisted[0].old_value, persisted[0].new_value) == (
        "calories",
        200.0,
        250.0,
    )


def test_last_edit_wins_and_estimated_never_changes(client: TestClient, db_engine: Engine) -> None:
    user_id, _ = register(client, "lastwins@example.com")
    item_id = seed_food_item(db_engine, user_id, calories=200.0)

    _edit(db_engine, user_id, CandidateType.FOOD, item_id, "calories", 250.0)
    item, _returned, persisted = _edit(
        db_engine, user_id, CandidateType.FOOD, item_id, "calories", 220.0
    )

    assert item.calories == 220.0
    # The estimated original is still the very first value, after two edits.
    assert item.calories_estimated == 200.0
    # Two correction rows form the audit trail; the second edit's old value chains
    # off the first edit's new value (append-only history, not an overwrite).
    pairs = {(c.old_value, c.new_value) for c in persisted if c.field == "calories"}
    assert pairs == {(200.0, 250.0), (250.0, 220.0)}


def test_snapshot_on_first_edit_when_not_pre_populated(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, _ = register(client, "snapshot@example.com")
    # A pre-migration item: current value present, estimated still NULL.
    item_id = seed_food_item(db_engine, user_id, calories=200.0, snapshot=False)

    item, _returned, _persisted = _edit(
        db_engine, user_id, CandidateType.FOOD, item_id, "calories", 180.0
    )

    # The first edit snapshots the prior current value as the original.
    assert item.calories == 180.0
    assert item.calories_estimated == 200.0
