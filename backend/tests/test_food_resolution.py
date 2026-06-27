"""End-to-end persistence tests for the food resolver through the worker (FTY-044).

Drive :func:`app.estimator.processing.process_estimation` with the real
:class:`ParseStep` + :class:`FoodResolveStep` (parse backed by the network-free
:class:`FakeProvider`, FDC backed by a stubbed :class:`FoodSource`) against the
migrated SQLite database, proving the acceptance criteria across the trust boundary:
a found generic food with a resolvable quantity becomes a ``resolved``
``derived_food_items`` row carrying canonical calories/macros, a cached global
``products`` row, and a user-owned ``evidence_sources`` row; an unknown food or an
unresolvable quantity routes to ``needs_clarification`` with nothing user-owned
persisted; a repeated food hits the cache instead of the source; and an unconfigured
source leaves food unresolved.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import DerivedItemStatus, EstimationJobStatus, LogEventStatus
from app.estimator.fdc import FDC_SOURCE, FDC_SOURCE_TYPE, FdcTransientError, ProductFacts
from app.estimator.food_serving import NutritionFacts
from app.estimator.food_step import FoodResolver, FoodResolveStep
from app.estimator.parse import ParseStep
from app.estimator.pipeline import Pipeline
from app.estimator.processing import process_estimation
from app.llm.providers.fake import FakeProvider
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource, Product


def _rice_facts() -> ProductFacts:
    """Stub USDA facts for white rice: clean per-100g values for exact assertions."""

    return ProductFacts(
        source=FDC_SOURCE,
        source_ref="usda_fdc:168880",
        query_key="white rice",
        description="Rice, white, cooked",
        facts=NutritionFacts(calories=130.0, protein_g=2.0, carbs_g=28.0, fat_g=0.2),
        default_serving_g=158.0,
        content_hash="ricehash",
    )


class FakeFoodSource:
    """A scripted, network-free :class:`FoodSource` for the resolver tests."""

    def __init__(
        self,
        facts: dict[str, ProductFacts] | None = None,
        *,
        enabled: bool = True,
        error: Exception | None = None,
    ) -> None:
        self._facts = facts or {}
        self._enabled = enabled
        self._error = error
        self.lookups: list[str] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def lookup(self, query: str) -> ProductFacts | None:
        self.lookups.append(query)
        if self._error is not None:
            raise self._error
        return self._facts.get(query.strip().lower())


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _pipeline(session: Session, source: FakeFoodSource, item: dict[str, object]) -> Pipeline:
    """A real parse + food-resolution pipeline whose provider returns one parsed food."""

    provider = FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": [item]}]
    )
    resolver = FoodResolver(session=session, source=source)
    return Pipeline([ParseStep(provider), FoodResolveStep(resolver)])


def _seed_event(
    client: TestClient, email: str, raw_text: str = "150g rice"
) -> tuple[uuid.UUID, uuid.UUID]:
    reg = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert reg.status_code == 201
    user_id = uuid.UUID(reg.json()["user"]["id"])
    auth = f"Bearer {reg.json()['token']['access_token']}"
    created = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": raw_text},
    )
    assert created.status_code == 201
    return user_id, uuid.UUID(created.json()["id"])


def _foods(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    )


def test_food_resolves_with_calories_macros_evidence_and_cache(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "food-ok@example.com")
    source = FakeFoodSource({"white rice": _rice_facts()})
    pipeline = _pipeline(
        session,
        source,
        {"type": "food", "name": "white rice", "quantity_text": "150g", "unit": "g", "amount": 150},
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED

    foods = _foods(session, event_id)
    assert len(foods) == 1
    food = foods[0]
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.user_id == user_id
    assert food.grams == 150.0
    # 150 g of 130 kcal / 2.0 P / 28 C / 0.2 F per-100g rice.
    assert food.calories == 195.0
    assert food.protein_g == 3.0
    assert food.carbs_g == 42.0
    assert food.fat_g == pytest.approx(0.3)

    # A global product cache row was created (no user ownership on it).
    product = session.scalars(select(Product).where(Product.query_key == "white rice")).one()
    assert product.source == FDC_SOURCE
    assert product.calories_per_100g == 130.0

    # A user-owned evidence row records the provenance + per-100g snapshot, not a page.
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).one()
    assert evidence.user_id == user_id
    assert evidence.derived_food_item_id == food.id
    assert evidence.product_id == product.id
    assert evidence.source_type == FDC_SOURCE_TYPE
    assert evidence.source_ref == "usda_fdc:168880"
    assert evidence.content_hash == "ricehash"
    assert evidence.calories_per_100g == 130.0


def test_unknown_food_needs_clarification(client: TestClient, session: Session) -> None:
    user_id, event_id = _seed_event(client, "food-unknown@example.com")
    source = FakeFoodSource({})  # nothing matches
    pipeline = _pipeline(
        session,
        source,
        {"type": "food", "name": "zorblax", "quantity_text": "150g", "unit": "g", "amount": 150},
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION
    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
    assert _foods(session, event_id) == []
    assert session.scalars(select(EvidenceSource)).all() == []


def test_unresolvable_quantity_needs_clarification(client: TestClient, session: Session) -> None:
    # A count with no default serving size cannot be resolved to grams; ask, never guess.
    user_id, event_id = _seed_event(client, "food-qty@example.com")
    soup = ProductFacts(
        source=FDC_SOURCE,
        source_ref="usda_fdc:1",
        query_key="soup",
        description="Soup",
        facts=NutritionFacts(calories=50.0, protein_g=2.0, carbs_g=5.0, fat_g=1.0),
        default_serving_g=None,
        content_hash="souphash",
    )
    pipeline = _pipeline(
        session,
        FakeFoodSource({"soup": soup}),
        {"type": "food", "name": "soup", "quantity_text": "two", "amount": 2},
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION
    assert _foods(session, event_id) == []


def test_repeated_food_uses_cache_not_source(client: TestClient, session: Session) -> None:
    source = FakeFoodSource({"white rice": _rice_facts()})
    item = {
        "type": "food",
        "name": "white rice",
        "quantity_text": "150g",
        "unit": "g",
        "amount": 150,
    }

    user_a, event_a = _seed_event(client, "cache-a@example.com")
    first = process_estimation(
        session, log_event_id=event_a, user_id=user_a, pipeline=_pipeline(session, source, item)
    )
    user_b, event_b = _seed_event(client, "cache-b@example.com")
    second = process_estimation(
        session, log_event_id=event_b, user_id=user_b, pipeline=_pipeline(session, source, item)
    )

    assert first.event_status is LogEventStatus.COMPLETED
    assert second.event_status is LogEventStatus.COMPLETED
    # The source was queried once; the second resolution hit the products cache.
    assert source.lookups == ["white rice"]
    # Exactly one global cache row exists despite two resolutions.
    assert len(session.scalars(select(Product).where(Product.query_key == "white rice")).all()) == 1


def test_transient_source_error_is_retryable(client: TestClient, session: Session) -> None:
    user_id, event_id = _seed_event(client, "food-transient@example.com")
    source = FakeFoodSource(error=FdcTransientError("fdc_transient_error"))
    pipeline = _pipeline(
        session,
        source,
        {"type": "food", "name": "white rice", "quantity_text": "150g", "unit": "g", "amount": 150},
    )

    result = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=pipeline, max_attempts=3
    )

    # A transient source failure leaves the job retryable, not terminal.
    assert result.should_retry is True
    assert result.job_status is EstimationJobStatus.RUNNING


def test_disabled_source_leaves_food_unresolved(client: TestClient, session: Session) -> None:
    user_id, event_id = _seed_event(client, "food-disabled@example.com")
    source = FakeFoodSource(enabled=False)
    pipeline = _pipeline(
        session,
        source,
        {"type": "food", "name": "white rice", "quantity_text": "150g", "unit": "g", "amount": 150},
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    # With no source configured the event still completes; food stays unresolved.
    assert result.event_status is LogEventStatus.COMPLETED
    foods = _foods(session, event_id)
    assert len(foods) == 1
    assert foods[0].status == DerivedItemStatus.UNRESOLVED
    assert foods[0].calories is None
    assert source.lookups == []
    assert session.scalars(select(EvidenceSource)).all() == []
