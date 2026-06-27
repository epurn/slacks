"""Append-only immutability/tamper test for ``corrections`` (FTY-051).

Proves the acceptance criterion that a correction cannot be updated or deleted
through the application: the ORM guards reject both, and the persisted row is
unchanged after a rejected attempt.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.enums import CandidateType, CorrectionSource
from app.models.corrections import Correction, CorrectionImmutableError
from tests.corrections_helpers import register, seed_food_item


def _seed_correction(db_engine: Engine, user_id: str, item_id: uuid.UUID) -> uuid.UUID:
    factory = create_session_factory(db_engine)
    with factory() as session:
        correction = Correction(
            user_id=uuid.UUID(user_id),
            item_type=CandidateType.FOOD,
            derived_food_item_id=item_id,
            field="calories",
            old_value=200.0,
            new_value=180.0,
            source=CorrectionSource.USER_EDIT,
        )
        session.add(correction)
        session.commit()
        return correction.id


def test_update_is_rejected(client: TestClient, db_engine: Engine) -> None:
    user_id, _ = register(client, "tamper-update@example.com")
    item_id = seed_food_item(db_engine, user_id)
    correction_id = _seed_correction(db_engine, user_id, item_id)

    factory = create_session_factory(db_engine)
    with factory() as session:
        correction = session.get(Correction, correction_id)
        assert correction is not None
        correction.new_value = 9999.0
        with pytest.raises(CorrectionImmutableError):
            session.commit()

    # The audit row is unchanged.
    with factory() as session:
        correction = session.get(Correction, correction_id)
        assert correction is not None
        assert correction.new_value == 180.0


def test_delete_is_rejected(client: TestClient, db_engine: Engine) -> None:
    user_id, _ = register(client, "tamper-delete@example.com")
    item_id = seed_food_item(db_engine, user_id)
    correction_id = _seed_correction(db_engine, user_id, item_id)

    factory = create_session_factory(db_engine)
    with factory() as session:
        correction = session.get(Correction, correction_id)
        assert correction is not None
        session.delete(correction)
        with pytest.raises(CorrectionImmutableError):
            session.commit()

    # The audit row still exists.
    with factory() as session:
        assert session.get(Correction, correction_id) is not None
