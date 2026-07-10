"""End-to-end persistence tests for the food resolver through the worker (FTY-044).

Drive :func:`app.estimator.processing.process_estimation` with the real
:class:`ParseStep` + :class:`FoodResolveStep` (parse backed by the network-free
:class:`FakeProvider`, FDC backed by a stubbed :class:`FoodSource`) against the
migrated SQLite database, proving the acceptance criteria across the trust boundary:
a found generic food with a resolvable quantity becomes a ``resolved``
``derived_food_items`` row carrying canonical calories/macros, a cached global
``products`` row, and a user-owned ``evidence_sources`` row; an unknown food or an
unresolvable quantity falls forward under estimate-first and is persisted unresolved
when this focused pipeline omits the rough-estimate step; a repeated food hits the
cache instead of the source; and an unconfigured source leaves food unresolved.
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
from app.estimator.pipeline import CandidateDraft, EstimationContext, Pipeline
from app.estimator.processing import process_estimation
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
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


def _compliments_strips_facts(*, default_serving_g: float | None) -> ProductFacts:
    """Brand-compatible packaged-product FDC row for FoodResolveStep routing tests."""

    return ProductFacts(
        source=FDC_SOURCE,
        source_ref="usda_fdc:compliments-strips",
        query_key="chicken strips",
        description="Compliments Chicken Strips",
        facts=NutritionFacts(calories=250.0, protein_g=12.0, carbs_g=20.0, fat_g=11.0),
        default_serving_g=default_serving_g,
        content_hash="compliments-strip-hash",
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
        * SELF_CONSISTENCY_FIRST_WINDOW
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


def test_unknown_food_without_detail_completes_unresolved_without_rough_step(
    client: TestClient, session: Session
) -> None:
    # Estimate-first defers even an amountless recognized candidate to the rough
    # official/reference/model-prior step. This focused pipeline omits that step, so
    # the worker persists the leftover candidate unresolved and completes rather than
    # asking the generic quantity question.
    user_id, event_id = _seed_event(client, "food-unknown@example.com")
    source = FakeFoodSource({})  # nothing matches
    pipeline = _pipeline(
        session,
        source,
        {"type": "food", "name": "zorblax"},  # no amount / count / range / measure
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    foods = _foods(session, event_id)
    assert len(foods) == 1
    assert foods[0].status == DerivedItemStatus.UNRESOLVED
    assert foods[0].calories is None
    assert session.scalars(select(EvidenceSource)).all() == []


def test_detailed_generic_miss_defers_instead_of_clarifying(
    client: TestClient, session: Session
) -> None:
    # FTY-167: a detail-rich generic food (identity + amount) USDA cannot cost no
    # longer clarifies. With no official/model-prior step wired it is left
    # ``unresolved`` and the event completes (in production the official step gives
    # it a model-prior estimate) — never a dead-end clarification.
    user_id, event_id = _seed_event(client, "food-detailed-miss@example.com")
    source = FakeFoodSource({})  # nothing matches
    pipeline = _pipeline(
        session,
        source,
        {"type": "food", "name": "donair pizza", "quantity_text": "a slice", "amount": 1},
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    foods = _foods(session, event_id)
    assert len(foods) == 1
    assert foods[0].status == DerivedItemStatus.UNRESOLVED
    assert foods[0].calories is None


def test_unresolvable_quantity_completes_unresolved_without_rough_step(
    client: TestClient, session: Session
) -> None:
    # A count with no source default serving size now falls forward under
    # estimate-first. With no rough-estimate step wired here, it completes as an
    # unresolved leftover instead of persisting a quantity question.
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

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    foods = _foods(session, event_id)
    assert len(foods) == 1
    assert foods[0].status == DerivedItemStatus.UNRESOLVED


def test_strict_branded_fdc_quantity_gap_defers_instead_of_clarifying(
    session: Session,
) -> None:
    # FTY-253: even in strict mode, a branded database hit is accepted only when
    # it is both brand-compatible and quantity-costable. A compatible row with no
    # serving grams for "4 strips" is a miss for routing, so the branded
    # official/reference/model-prior tiers get the candidate instead of the
    # generic quantity question.
    candidate = CandidateDraft(
        name="chicken strips",
        brand="Compliments",
        quantity_text="i had 4",
        unit="strips",
        amount=4,
    )
    context = EstimationContext(
        log_event_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        raw_text="compliments brand chicken strips (i had 4)",
        food_candidates=[candidate],
    )
    source = FakeFoodSource({"chicken strips": _compliments_strips_facts(default_serving_g=None)})
    step = FoodResolveStep(
        FoodResolver(session=session, source=source),
        clarify_mode="strict",
    )

    step.run(context)

    assert source.lookups == ["chicken strips"]
    assert context.resolved_food_items == []
    assert context.pending_official_candidates == [candidate]
    assert context.clarification_questions == []


def test_branded_fdc_match_must_be_costable_before_it_skips_official(
    session: Session,
) -> None:
    # The replacement for the former "branded USDA skips official" invariant:
    # USDA still wins when the row matches the branded identity and can cost the
    # logged amount. Otherwise the previous test proves it defers.
    candidate = CandidateDraft(
        name="chicken strips",
        brand="Compliments",
        quantity_text="i had 4",
        unit="strips",
        amount=4,
    )
    context = EstimationContext(
        log_event_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        raw_text="compliments brand chicken strips (i had 4)",
        food_candidates=[candidate],
    )
    source = FakeFoodSource({"chicken strips": _compliments_strips_facts(default_serving_g=95.0)})
    step = FoodResolveStep(
        FoodResolver(session=session, source=source),
        clarify_mode="strict",
    )

    step.run(context)

    assert context.pending_official_candidates == []
    assert context.clarification_questions == []
    [item] = context.resolved_food_items
    assert item.source_type == FDC_SOURCE_TYPE
    assert item.source_ref == "usda_fdc:compliments-strips"
    assert item.grams == 380.0
    assert item.calories == 950.0


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


def _seed_cached_product(
    session: Session,
    *,
    query_key: str,
    description: str,
    source_ref: str,
    calories: float,
) -> Product:
    """A pre-existing global FDC cache row, as an upgraded database would hold it."""

    product = Product(
        source=FDC_SOURCE,
        source_ref=source_ref,
        query_key=query_key,
        description=description,
        calories_per_100g=calories,
        protein_per_100g=1.0,
        carbs_per_100g=10.0,
        fat_per_100g=0.5,
        content_hash=f"stale-{source_ref}",
    )
    session.add(product)
    session.flush()
    return product


def test_stale_incompatible_cached_product_is_refreshed_from_the_source(session: Session) -> None:
    """FTY-254 upgrade path: a database that already cached ``banana`` to the
    dehydrated/powder row must not keep serving it. The cached row fails today's
    compatibility gate, the ranked source lookup runs, and the single cache row
    is refreshed in place with the compatible selection."""

    stale = _seed_cached_product(
        session,
        query_key="banana",
        description="Bananas, dehydrated, or banana powder",
        source_ref="usda_fdc:9041",
        calories=346.0,
    )
    fresh = ProductFacts(
        source=FDC_SOURCE,
        source_ref="usda_fdc:9040",
        query_key="banana",
        description="Bananas, raw",
        facts=NutritionFacts(calories=89.0, protein_g=1.09, carbs_g=22.84, fat_g=0.33),
        default_serving_g=118.0,
        content_hash="fresh-banana-hash",
    )
    source = FakeFoodSource({"banana": fresh})
    resolver = FoodResolver(session=session, source=source)

    resolved = resolver.resolve_product("banana")

    assert resolved is not None
    # The stale row was not trusted: the source was consulted again.
    assert source.lookups == ["banana"]
    # Refreshed in place — same row (the (source, query_key) key allows one),
    # now carrying the compatible fresh-banana facts.
    assert resolved.product.id == stale.id
    assert resolved.product.source_ref == "usda_fdc:9040"
    assert resolved.product.description == "Bananas, raw"
    assert resolved.product.calories_per_100g == pytest.approx(89.0)
    assert resolved.product.default_serving_g == pytest.approx(118.0)
    assert resolved.product.content_hash == "fresh-banana-hash"
    assert len(session.scalars(select(Product).where(Product.query_key == "banana")).all()) == 1


def test_stale_incompatible_cached_product_is_a_miss_without_a_compatible_row(
    session: Session,
) -> None:
    """``dill pickle hummus`` cached to the pickles row pre-FTY-254 is rejected
    on read; when the source has no compatible row either, the resolution is a
    clean miss (falling forward to the rough tiers), never the pickles facts."""

    _seed_cached_product(
        session,
        query_key="dill pickle hummus",
        description="Pickles, cucumber, dill or kosher dill",
        source_ref="usda_fdc:11937",
        calories=11.0,
    )
    source = FakeFoodSource({})
    resolver = FoodResolver(session=session, source=source)

    assert resolver.resolve_product("dill pickle hummus") is None
    assert source.lookups == ["dill pickle hummus"]


def test_compatible_cached_product_is_served_without_an_external_call(session: Session) -> None:
    cached = _seed_cached_product(
        session,
        query_key="banana",
        description="Bananas, raw",
        source_ref="usda_fdc:9040",
        calories=89.0,
    )
    source = FakeFoodSource({})
    resolver = FoodResolver(session=session, source=source)

    resolved = resolver.resolve_product("banana")

    assert resolved is not None
    assert resolved.product.id == cached.id
    assert source.lookups == []


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
