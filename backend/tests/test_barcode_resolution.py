"""End-to-end persistence tests for the barcode (OFF) resolver via the worker (FTY-060).

Drive :func:`app.estimator.processing.process_estimation` with the real
:class:`ParseStep` + :class:`FoodResolveStep` (parse backed by the network-free
:class:`FakeProvider`, sources backed by stubbed fakes) against the migrated SQLite
database, proving the acceptance criteria across the barcode trust boundary:

- a barcode-bearing candidate resolves to a ``resolved`` ``derived_food_items`` row
  with calories/macros computed from OFF facts, a global ``products`` row keyed by
  barcode, and a user-owned ``evidence_sources`` row (``product_database``);
- a repeat scan hits the cache and makes **no** external call;
- a confident OFF match is preferred over generic USDA lookup for the same input;
- a barcode OFF cannot resolve falls forward under estimate-first and is persisted
  unresolved when this focused pipeline omits the rough-estimate step;
- when OFF is disabled, a barcode candidate falls back to the next source (USDA);
- only the mapped facts (not the raw response) are persisted.
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
from app.estimator.fdc import FDC_SOURCE, FDC_SOURCE_TYPE, ProductFacts
from app.estimator.food_resolvers import BarcodeResolver, FoodResolver
from app.estimator.food_serving import NutritionFacts
from app.estimator.food_step import FoodResolveStep
from app.estimator.off import (
    OFF_SOURCE,
    OFF_SOURCE_TYPE,
    OffTransientError,
    normalize_barcode,
)
from app.estimator.parse import ParseStep
from app.estimator.pipeline import Pipeline
from app.estimator.processing import process_estimation
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.providers.fake import FakeProvider
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource, Product

_BARCODE = "0123456789012"


def _cola_facts() -> ProductFacts:
    """Stub OFF facts for a cola: clean per-100g values for exact assertions."""

    return ProductFacts(
        source=OFF_SOURCE,
        source_ref=f"{OFF_SOURCE}:{_BARCODE}",
        query_key=_BARCODE,
        description="Cola",
        facts=NutritionFacts(calories=42.0, protein_g=0.0, carbs_g=10.6, fat_g=0.1),
        default_serving_g=330.0,
        content_hash="colahash",
        barcode=_BARCODE,
    )


def _rice_facts() -> ProductFacts:
    """Stub USDA facts for white rice, used to prove OFF wins the source hierarchy."""

    return ProductFacts(
        source=FDC_SOURCE,
        source_ref="usda_fdc:168880",
        query_key="white rice",
        description="Rice, white, cooked",
        facts=NutritionFacts(calories=130.0, protein_g=2.0, carbs_g=28.0, fat_g=0.2),
        default_serving_g=158.0,
        content_hash="ricehash",
    )


class FakeBarcodeSource:
    """A scripted, network-free barcode source for the resolver tests."""

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

    def lookup(self, barcode: str) -> ProductFacts | None:
        self.lookups.append(barcode)
        if self._error is not None:
            raise self._error
        return self._facts.get(normalize_barcode(barcode) or "")


class FakeFoodSource:
    """A scripted, network-free generic (FDC) source for the resolver tests."""

    def __init__(
        self, facts: dict[str, ProductFacts] | None = None, *, enabled: bool = True
    ) -> None:
        self._facts = facts or {}
        self._enabled = enabled
        self.lookups: list[str] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def lookup(self, query: str) -> ProductFacts | None:
        self.lookups.append(query)
        return self._facts.get(query.strip().lower())


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _pipeline(
    session: Session,
    *,
    off_source: FakeBarcodeSource,
    fdc_source: FakeFoodSource,
    item: dict[str, object],
) -> Pipeline:
    """A real parse + food-resolution pipeline whose provider returns one food item."""

    provider = FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": [item]}]
        * SELF_CONSISTENCY_FIRST_WINDOW
    )
    resolver = FoodResolver(session=session, source=fdc_source)
    barcode_resolver = BarcodeResolver(session=session, source=off_source)
    step = FoodResolveStep(resolver, barcode_resolver=barcode_resolver)
    return Pipeline([ParseStep(provider), step])


def _seed_event(client: TestClient, email: str) -> tuple[uuid.UUID, uuid.UUID]:
    reg = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert reg.status_code == 201
    user_id = uuid.UUID(reg.json()["user"]["id"])
    auth = f"Bearer {reg.json()['token']['access_token']}"
    created = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "a scanned product"},
    )
    assert created.status_code == 201
    return user_id, uuid.UUID(created.json()["id"])


def _foods(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    )


def test_barcode_resolves_with_calories_evidence_and_cache(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "barcode-ok@example.com")
    off = FakeBarcodeSource({_BARCODE: _cola_facts()})
    fdc = FakeFoodSource()
    pipeline = _pipeline(
        session,
        off_source=off,
        fdc_source=fdc,
        item={
            "type": "food",
            "name": "cola",
            "quantity_text": "200g",
            "unit": "g",
            "amount": 200,
            "barcode": _BARCODE,
        },
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED

    foods = _foods(session, event_id)
    assert len(foods) == 1
    food = foods[0]
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.grams == 200.0
    # 200 g of 42 kcal / 0 P / 10.6 C / 0.1 F per-100g cola.
    assert food.calories == 84.0
    assert food.carbs_g == pytest.approx(21.2)
    assert food.fat_g == pytest.approx(0.2)

    # A global product cache row keyed by barcode (no user ownership on it).
    product = session.scalars(select(Product).where(Product.barcode == _BARCODE)).one()
    assert product.source == OFF_SOURCE
    assert product.query_key == _BARCODE
    assert product.calories_per_100g == 42.0

    # A user-owned evidence row records the provenance + per-100g snapshot, not a page.
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).one()
    assert evidence.user_id == user_id
    assert evidence.product_id == product.id
    assert evidence.source_type == OFF_SOURCE_TYPE
    assert evidence.source_ref == f"{OFF_SOURCE}:{_BARCODE}"
    assert evidence.content_hash == "colahash"
    assert evidence.calories_per_100g == 42.0
    # The FDC generic source was never consulted for a barcode candidate.
    assert fdc.lookups == []


def test_repeat_scan_uses_cache_not_source(client: TestClient, session: Session) -> None:
    off = FakeBarcodeSource({_BARCODE: _cola_facts()})
    item = {
        "type": "food",
        "name": "cola",
        "quantity_text": "200g",
        "unit": "g",
        "amount": 200,
        "barcode": _BARCODE,
    }

    user_a, event_a = _seed_event(client, "scan-a@example.com")
    first = process_estimation(
        session,
        log_event_id=event_a,
        user_id=user_a,
        pipeline=_pipeline(session, off_source=off, fdc_source=FakeFoodSource(), item=item),
    )
    user_b, event_b = _seed_event(client, "scan-b@example.com")
    second = process_estimation(
        session,
        log_event_id=event_b,
        user_id=user_b,
        pipeline=_pipeline(session, off_source=off, fdc_source=FakeFoodSource(), item=item),
    )

    assert first.event_status is LogEventStatus.COMPLETED
    assert second.event_status is LogEventStatus.COMPLETED
    # OFF was queried exactly once; the second scan hit the products cache.
    assert off.lookups == [_BARCODE]
    assert len(session.scalars(select(Product).where(Product.barcode == _BARCODE)).all()) == 1


def test_off_match_wins_over_generic_usda_for_same_input(
    client: TestClient, session: Session
) -> None:
    # Same candidate matches both a barcode (OFF) and a name (USDA); OFF must win.
    user_id, event_id = _seed_event(client, "hierarchy@example.com")
    off = FakeBarcodeSource({_BARCODE: _cola_facts()})
    fdc = FakeFoodSource({"white rice": _rice_facts()})
    pipeline = _pipeline(
        session,
        off_source=off,
        fdc_source=fdc,
        item={
            "type": "food",
            "name": "white rice",
            "quantity_text": "200g",
            "unit": "g",
            "amount": 200,
            "barcode": _BARCODE,
        },
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).one()
    # Resolved from the packaged-product source, not the generic database.
    assert evidence.source_type == OFF_SOURCE_TYPE
    assert evidence.source_ref == f"{OFF_SOURCE}:{_BARCODE}"
    # 200 g of the OFF cola facts (42 kcal/100g), not the USDA rice (130 kcal/100g).
    assert _foods(session, event_id)[0].calories == 84.0
    assert fdc.lookups == []


def test_unknown_barcode_completes_unresolved_without_rough_step(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "barcode-unknown@example.com")
    off = FakeBarcodeSource({})  # nothing matches
    pipeline = _pipeline(
        session,
        off_source=off,
        fdc_source=FakeFoodSource(),
        item={
            "type": "food",
            "name": "mystery",
            "quantity_text": "200g",
            "unit": "g",
            "amount": 200,
            "barcode": _BARCODE,
        },
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    foods = _foods(session, event_id)
    assert len(foods) == 1
    assert foods[0].status == DerivedItemStatus.UNRESOLVED
    assert session.scalars(select(EvidenceSource)).all() == []


def test_disabled_off_falls_back_to_generic_usda(client: TestClient, session: Session) -> None:
    # With OFF off, a barcode candidate falls back to the next source (USDA by name).
    user_id, event_id = _seed_event(client, "off-disabled@example.com")
    off = FakeBarcodeSource({_BARCODE: _cola_facts()}, enabled=False)
    fdc = FakeFoodSource({"white rice": _rice_facts()})
    pipeline = _pipeline(
        session,
        off_source=off,
        fdc_source=fdc,
        item={
            "type": "food",
            "name": "white rice",
            "quantity_text": "200g",
            "unit": "g",
            "amount": 200,
            "barcode": _BARCODE,
        },
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).one()
    assert evidence.source_type == FDC_SOURCE_TYPE
    assert off.lookups == []  # the disabled source was never queried


def test_transient_off_error_is_retryable(client: TestClient, session: Session) -> None:
    user_id, event_id = _seed_event(client, "barcode-transient@example.com")
    off = FakeBarcodeSource(error=OffTransientError("off_transient_error"))
    pipeline = _pipeline(
        session,
        off_source=off,
        fdc_source=FakeFoodSource(),
        item={
            "type": "food",
            "name": "cola",
            "quantity_text": "200g",
            "unit": "g",
            "amount": 200,
            "barcode": _BARCODE,
        },
    )

    result = process_estimation(
        session, log_event_id=event_id, user_id=user_id, pipeline=pipeline, max_attempts=3
    )

    assert result.should_retry is True
    assert result.job_status is EstimationJobStatus.RUNNING
