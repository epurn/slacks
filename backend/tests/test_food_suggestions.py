"""Contextual food-suggestion endpoint tests (FTY-340)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.deps import get_current_time
from app.enums import DerivedItemStatus, LogEventStatus, SavedFoodSource
from app.models.derived import DerivedFoodItem
from app.models.log_events import LogEvent
from app.models.saved_foods import FoodAlias, SavedFood
from app.normalization import normalize_text
from app.services import food_suggestions as food_suggestions_service
from tests.corrections_helpers import register


def _auth_get(client: TestClient, auth: str, *, limit: int | None = None) -> httpx.Response:
    params = {} if limit is None else {"limit": limit}
    return cast(
        httpx.Response,
        client.get("/api/food-suggestions", headers={"Authorization": auth}, params=params),
    )


@contextmanager
def _pinned_now(client: TestClient, now: datetime) -> Iterator[None]:
    app = cast(FastAPI, client.app)
    app.dependency_overrides[get_current_time] = lambda: now
    try:
        yield
    finally:
        app.dependency_overrides.pop(get_current_time, None)


def _seed_food_event(
    db_engine: Engine,
    user_id: str,
    *,
    label: str,
    happened_at: datetime,
    status: LogEventStatus = LogEventStatus.COMPLETED,
    item_status: DerivedItemStatus = DerivedItemStatus.RESOLVED,
    voided: bool = False,
) -> uuid.UUID:
    factory = create_session_factory(db_engine)
    with factory() as session:
        event = LogEvent(
            user_id=uuid.UUID(user_id),
            raw_text=label,
            status=status,
            created_at=happened_at,
            updated_at=happened_at,
            voided_at=happened_at if voided else None,
        )
        session.add(event)
        session.flush()
        item = DerivedFoodItem(
            log_event_id=event.id,
            user_id=uuid.UUID(user_id),
            name=label,
            quantity_text="1 serving",
            status=item_status,
            grams=100.0,
            calories=100.0,
            protein_g=1.0,
            carbs_g=10.0,
            fat_g=1.0,
            calories_estimated=100.0,
            protein_g_estimated=1.0,
            carbs_g_estimated=10.0,
            fat_g_estimated=1.0,
            created_at=happened_at,
            updated_at=happened_at,
        )
        session.add(item)
        session.commit()
        return item.id


def _seed_saved_food(
    db_engine: Engine,
    user_id: str,
    *,
    name: str,
    alias: str,
    created_at: datetime,
) -> uuid.UUID:
    factory = create_session_factory(db_engine)
    with factory() as session:
        saved_food = SavedFood(
            user_id=uuid.UUID(user_id),
            name=name,
            name_normalized=normalize_text(name),
            calories=200.0,
            protein_g=10.0,
            carbs_g=20.0,
            fat_g=5.0,
            serving_size=1.0,
            serving_unit="serving",
            source=SavedFoodSource.SAVED_FROM_CORRECTION,
            created_at=created_at,
            updated_at=created_at,
        )
        session.add(saved_food)
        session.flush()
        session.add(
            FoodAlias(
                user_id=uuid.UUID(user_id),
                saved_food_id=saved_food.id,
                alias=alias,
                alias_normalized=normalize_text(alias),
                created_at=created_at,
                updated_at=created_at,
            )
        )
        session.commit()
        return saved_food.id


def test_suggestions_shift_between_weekday_morning_and_weekend_evening(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "context-shift@example.com")
    base_monday = datetime(2026, 6, 22, 8, 0, tzinfo=UTC)
    for day_offset in [0, 1, 2, 3, 4, 7, 8, 9]:
        _seed_food_event(
            db_engine,
            user_id,
            label="oatmeal",
            happened_at=base_monday + timedelta(days=day_offset),
        )
    base_saturday = datetime(2026, 6, 21, 20, 0, tzinfo=UTC)
    for day_offset in [0, 6, 7, 13, 14, 20, 21, 27]:
        _seed_food_event(
            db_engine,
            user_id,
            label="pizza",
            happened_at=base_saturday + timedelta(days=day_offset),
        )

    with _pinned_now(client, datetime(2026, 7, 7, 8, 0, tzinfo=UTC)):
        morning = _auth_get(client, auth, limit=2)
    with _pinned_now(client, datetime(2026, 7, 11, 20, 0, tzinfo=UTC)):
        evening = _auth_get(client, auth, limit=2)

    assert morning.status_code == 200
    assert evening.status_code == 200
    assert [item["label"] for item in morning.json()["items"]] == ["oatmeal", "pizza"]
    assert [item["label"] for item in evening.json()["items"]] == ["pizza", "oatmeal"]


def test_recent_regular_beats_frequent_old_history_and_all_day_favourite_survives_off_hours(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "frecency@example.com")
    now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    for days_ago in range(90, 110):
        _seed_food_event(
            db_engine,
            user_id,
            label="old protein bar",
            happened_at=now - timedelta(days=days_ago),
        )
    for days_ago in [1, 2, 3]:
        _seed_food_event(
            db_engine,
            user_id,
            label="recent chicken bowl",
            happened_at=now - timedelta(days=days_ago),
        )
    for days_ago in [1, 2, 3, 4, 5]:
        _seed_food_event(
            db_engine,
            user_id,
            label="all day yogurt",
            happened_at=now - timedelta(days=days_ago, hours=12),
        )

    with _pinned_now(client, now):
        response = _auth_get(client, auth, limit=3)

    assert response.status_code == 200
    labels = [item["label"] for item in response.json()["items"]]
    assert labels.index("recent chicken bowl") < labels.index("old protein bar")
    assert "all day yogurt" in labels


def test_saved_food_dedups_with_matching_history_and_preserves_saved_food_id(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = register(client, "dedup@example.com")
    now = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
    saved_food_id = _seed_saved_food(
        db_engine,
        user_id,
        name="Greek Yogurt",
        alias="yogurt cup",
        created_at=now - timedelta(days=10),
    )
    _seed_food_event(
        db_engine,
        user_id,
        label="yogurt cup",
        happened_at=now - timedelta(days=1),
    )

    with _pinned_now(client, now):
        response = _auth_get(client, auth, limit=8)

    assert response.status_code == 200
    matching = [item for item in response.json()["items"] if item["label"] == "Greek Yogurt"]
    assert len(matching) == 1
    assert matching[0]["submit_phrase"] == "yogurt cup"
    assert matching[0]["saved_food_id"] == str(saved_food_id)


def test_tie_breaks_by_most_recent_then_label(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id, auth = register(client, "tie-break@example.com")
    now = datetime(2026, 7, 10, 12, 0, tzinfo=UTC)
    _seed_food_event(db_engine, user_id, label="banana", happened_at=now - timedelta(days=5))
    _seed_food_event(db_engine, user_id, label="apple", happened_at=now - timedelta(days=5))
    _seed_food_event(db_engine, user_id, label="carrots", happened_at=now - timedelta(days=4))

    monkeypatch.setattr(food_suggestions_service, "_score_candidate", lambda *args: 1.0)
    with _pinned_now(client, now):
        response = _auth_get(client, auth, limit=3)

    assert response.status_code == 200
    assert [item["label"] for item in response.json()["items"]] == [
        "carrots",
        "apple",
        "banana",
    ]


def test_empty_history_returns_empty_list(client: TestClient, db_engine: Engine) -> None:
    _user_id, auth = register(client, "empty-suggestions@example.com")

    response = _auth_get(client, auth)

    assert response.status_code == 200
    assert response.json() == {"items": [], "limit": 8}


def test_limit_cap_is_enforced(client: TestClient, db_engine: Engine) -> None:
    _user_id, auth = register(client, "limit-cap@example.com")

    response = _auth_get(client, auth, limit=21)

    assert response.status_code == 422


def test_food_suggestions_are_owner_scoped(client: TestClient, db_engine: Engine) -> None:
    alice_id, alice_auth = register(client, "alice-suggestions@example.com")
    bob_id, _bob_auth = register(client, "bob-suggestions@example.com")
    now = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
    _seed_food_event(db_engine, alice_id, label="alice oats", happened_at=now - timedelta(days=1))
    _seed_food_event(db_engine, bob_id, label="bob secret", happened_at=now - timedelta(days=1))
    _seed_saved_food(
        db_engine,
        bob_id,
        name="Bob Saved Secret",
        alias="bob alias",
        created_at=now - timedelta(days=1),
    )

    with _pinned_now(client, now):
        response = _auth_get(client, alice_auth, limit=8)

    assert response.status_code == 200
    body_text = response.text
    assert "alice oats" in body_text
    assert "bob secret" not in body_text
    assert "Bob Saved Secret" not in body_text


def test_requires_authentication(client: TestClient) -> None:
    response = client.get("/api/food-suggestions")

    assert response.status_code == 401


def test_incomplete_or_voided_history_is_excluded(client: TestClient, db_engine: Engine) -> None:
    user_id, auth = register(client, "excluded-history@example.com")
    now = datetime(2026, 7, 10, 8, 0, tzinfo=UTC)
    _seed_food_event(db_engine, user_id, label="ready oats", happened_at=now - timedelta(days=1))
    _seed_food_event(
        db_engine,
        user_id,
        label="pending toast",
        happened_at=now - timedelta(days=1),
        status=LogEventStatus.PROCESSING,
    )
    _seed_food_event(
        db_engine,
        user_id,
        label="voided eggs",
        happened_at=now - timedelta(days=1),
        voided=True,
    )
    _seed_food_event(
        db_engine,
        user_id,
        label="proposed label",
        happened_at=now - timedelta(days=1),
        item_status=DerivedItemStatus.PROPOSED,
    )

    with _pinned_now(client, now):
        response = _auth_get(client, auth, limit=8)

    assert response.status_code == 200
    assert [item["label"] for item in response.json()["items"]] == ["ready oats"]
