"""Shared seeding helpers for the FTY-051 corrections tests.

Not a test module: it registers a user through the API and inserts resolved
derived food/exercise items directly via the session factory so the edit tests
have something to correct. ``snapshot`` controls whether the estimated/original
columns are pre-populated (the estimator path) or left ``None`` (a pre-migration
item that must snapshot on its first edit).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.enums import DerivedItemStatus, LogEventStatus
from app.models.derived import DerivedExerciseItem, DerivedFoodItem
from app.models.food_sources import EvidenceSource
from app.models.log_events import LogEvent


def register(client: TestClient, email: str) -> tuple[str, str]:
    """Register a user, returning ``(user_id, auth_header_value)``."""

    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": "a-good-password"},
    )
    assert resp.status_code == 201
    body = resp.json()
    return body["user"]["id"], f"Bearer {body['token']['access_token']}"


def _seed_event(db_engine: Engine, user_id: str) -> uuid.UUID:
    factory = create_session_factory(db_engine)
    with factory() as session:
        event = LogEvent(user_id=uuid.UUID(user_id), raw_text="seed", status=LogEventStatus.PENDING)
        session.add(event)
        session.commit()
        return event.id


def seed_food_item(
    db_engine: Engine,
    user_id: str,
    *,
    amount: float | None = 1.0,
    calories: float | None = 200.0,
    protein_g: float | None = 4.0,
    carbs_g: float | None = 44.0,
    fat_g: float | None = 0.4,
    snapshot: bool = True,
) -> uuid.UUID:
    """Insert a resolved ``derived_food_items`` row and return its id."""

    event_id = _seed_event(db_engine, user_id)
    factory = create_session_factory(db_engine)
    with factory() as session:
        item = DerivedFoodItem(
            log_event_id=event_id,
            user_id=uuid.UUID(user_id),
            name="white rice",
            quantity_text="1 serving",
            unit=None,
            amount=amount,
            status=DerivedItemStatus.RESOLVED,
            grams=150.0,
            calories=calories,
            protein_g=protein_g,
            carbs_g=carbs_g,
            fat_g=fat_g,
            calories_estimated=calories if snapshot else None,
            protein_g_estimated=protein_g if snapshot else None,
            carbs_g_estimated=carbs_g if snapshot else None,
            fat_g_estimated=fat_g if snapshot else None,
        )
        session.add(item)
        session.commit()
        return item.id


def seed_evidence(
    db_engine: Engine,
    user_id: str,
    item_id: uuid.UUID,
    *,
    source_type: str,
    source_ref: str,
    assumptions: list[str] | None = None,
    basis: str = "per_100g",
    field_provenance: dict[str, str] | None = None,
) -> uuid.UUID:
    """Insert a user-owned ``evidence_sources`` row for a derived food item.

    Lets the provenance read-model tests assert the source descriptor mapping and
    that an amount adjust leaves this snapshot untouched. Reuses the item's owning
    ``log_event_id`` so ownership cascades stay consistent. ``assumptions`` seeds the
    stored provenance list (e.g. to exercise the FTY-281 ``estimate_basis`` derivation).
    ``basis``/``field_provenance`` default to the ordinary database-source shape; pass
    non-default values to seed a stale ``as_logged``/heterogeneous row (e.g. for
    re-match provenance-reset tests).
    """

    factory = create_session_factory(db_engine)
    with factory() as session:
        item = session.get(DerivedFoodItem, item_id)
        assert item is not None
        evidence = EvidenceSource(
            user_id=uuid.UUID(user_id),
            log_event_id=item.log_event_id,
            derived_food_item_id=item_id,
            product_id=None,
            source_type=source_type,
            source_ref=source_ref,
            assumptions=assumptions,
            basis=basis,
            field_provenance=field_provenance,
            content_hash="0" * 64,
            fetched_at=datetime.now(UTC),
            calories_per_100g=130.0,
            protein_per_100g=2.7,
            carbs_per_100g=28.0,
            fat_per_100g=0.3,
        )
        session.add(evidence)
        session.commit()
        return evidence.id


def seed_exercise_item(
    db_engine: Engine,
    user_id: str,
    *,
    active_calories: float | None = 120.0,
    snapshot: bool = True,
) -> uuid.UUID:
    """Insert a resolved ``derived_exercise_items`` row and return its id."""

    event_id = _seed_event(db_engine, user_id)
    factory = create_session_factory(db_engine)
    with factory() as session:
        item = DerivedExerciseItem(
            log_event_id=event_id,
            user_id=uuid.UUID(user_id),
            name="running",
            quantity_text="30 minutes",
            unit=None,
            amount=30.0,
            status=DerivedItemStatus.RESOLVED,
            active_calories=active_calories,
            active_calories_estimated=active_calories if snapshot else None,
        )
        session.add(item)
        session.commit()
        return item.id
