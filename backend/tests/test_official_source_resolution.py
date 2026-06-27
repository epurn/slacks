"""End-to-end tests for the official-source resolution step through the worker (FTY-062).

Drive :func:`app.estimator.processing.process_estimation` with the real
:class:`ParseStep` + :class:`FoodResolveStep` + :class:`OfficialSourceResolveStep`
(parse/extraction backed by the network-free :class:`FakeProvider`, search by a
scripted fake adapter, fetch by a network-free fake fetcher) against the migrated
SQLite database, proving the acceptance criteria across the trust boundary:

- a branded product USDA/OFF cannot resolve is costed from an official page
  (search → fetch → extract → schema-validate → serving math) into a ``resolved``
  ``derived_food_items`` row plus an ``evidence_sources`` row carrying
  ``official_source:<url>``, a content hash, and the per-100g snapshot — never a raw
  page, and with no ``product_id``;
- the official step runs **only** for branded candidates and **only after** a
  USDA/OFF miss (a generic miss clarifies; a USDA-resolved branded item never
  searches);
- with the search provider disabled/unavailable, a branded product falls through to
  a model-prior estimate carrying ``source_type = model_prior`` and an explicit
  assumptions reason — never a silent guess;
- the step issues no direct egress: search flows through the injected adapter and
  fetch through the injected hardened fetcher.
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
from app.estimator.fdc import FDC_SOURCE, ProductFacts
from app.estimator.food_serving import NutritionFacts
from app.estimator.food_step import FoodResolver, FoodResolveStep
from app.estimator.official_fetch import OfficialFetchSettings
from app.estimator.official_step import (
    MODEL_PRIOR_SOURCE_TYPE,
    OfficialSourceResolveStep,
)
from app.estimator.parse import ParseStep
from app.estimator.pipeline import Pipeline
from app.estimator.processing import process_estimation
from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    SearchCandidate,
    SearchCapability,
    SearchResult,
    SearchStatus,
)
from app.llm.providers.fake import FakeProvider
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource, Product

_BIG_MAC_URL = "https://example.com/menu/big-mac"

# Canonical per-100g facts the official page / model prior "reports", chosen for exact
# serving-math assertions: 250 kcal / 10 P / 30 C / 9 F per 100 g, 219 g default serving.
_PAGE_FACTS = {
    "basis": "per_100g",
    "product_name": "Big Mac",
    "calories": 250.0,
    "protein_g": 10.0,
    "carbs_g": 30.0,
    "fat_g": 9.0,
    "serving_size_amount": 219.0,
    "serving_size_unit": "g",
}


class FakeFoodSource:
    """A scripted, network-free generic-food source (USDA stand-in)."""

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


class FakeSearchProvider:
    """A scripted, network-free :class:`SearchProvider` recording its queries."""

    def __init__(
        self,
        result: SearchResult,
        *,
        enabled: bool = True,
        available: bool = True,
    ) -> None:
        self._result = result
        self._enabled = enabled
        self._available = available
        self.queries: list[str] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def available(self) -> bool:
        return self._available

    @property
    def capability(self) -> SearchCapability:
        return SearchCapability(
            id="official_source",
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=("named_product", "restaurant_item"),
            enabled=self._enabled,
            available=self._available,
        )

    def search(self, query: str) -> SearchResult:
        self.queries.append(query)
        return self._result


class RecordingFetcher:
    """A network-free official-source fetcher recording the URLs it is handed."""

    def __init__(self, text: str = "Big Mac — 250 kcal per 100 g") -> None:
        self._text = text
        self.fetched: list[str] = []

    def __call__(self, url: str, settings: OfficialFetchSettings) -> str:
        self.fetched.append(url)
        return self._text


def _success_result(url: str = _BIG_MAC_URL) -> SearchResult:
    return SearchResult(
        status=SearchStatus.SUCCESS,
        candidates=(SearchCandidate(url=url, title="Big Mac | McDonald's"),),
    )


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _fetch_settings() -> OfficialFetchSettings:
    return OfficialFetchSettings(allowed_hosts=frozenset({"example.com"}))


def _pipeline(
    session: Session,
    *,
    food_source: FakeFoodSource,
    parsed_item: dict[str, object],
    search_provider: FakeSearchProvider,
    fetcher: RecordingFetcher,
    estimate: dict[str, object],
    fetch_settings: OfficialFetchSettings | None = None,
) -> Pipeline:
    """Real parse + food + official-source pipeline with all network seams faked."""

    parse_provider = FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": [parsed_item]}]
    )
    official_provider = FakeProvider(responses=[estimate])
    resolver = FoodResolver(session=session, source=food_source)
    official_step = OfficialSourceResolveStep(
        provider=official_provider,
        search_provider=search_provider,
        fetch_settings=fetch_settings or _fetch_settings(),
        fetch_fn=fetcher,
    )
    return Pipeline([ParseStep(parse_provider), FoodResolveStep(resolver), official_step])


def _seed_event(client: TestClient, email: str, raw_text: str) -> tuple[uuid.UUID, uuid.UUID]:
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


def _branded_item() -> dict[str, object]:
    return {
        "type": "food",
        "name": "Big Mac",
        "brand": "McDonald's",
        "quantity_text": "1",
        "amount": 1,
    }


def test_branded_food_resolves_from_official_source(client: TestClient, session: Session) -> None:
    user_id, event_id = _seed_event(client, "official-ok@example.com", "a Big Mac")
    search = FakeSearchProvider(_success_result())
    fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),  # USDA miss
        parsed_item=_branded_item(),
        search_provider=search,
        fetcher=fetcher,
        estimate={"disposition": "resolved", "confidence": 0.9, "facts": _PAGE_FACTS},
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED

    foods = _foods(session, event_id)
    assert len(foods) == 1
    food = foods[0]
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.grams == 219.0
    # 219 g of 250 kcal / 10 P / 30 C / 9 F per-100g.
    assert food.calories == 547.5
    assert food.protein_g == pytest.approx(21.9)
    assert food.carbs_g == pytest.approx(65.7)
    assert food.fat_g == pytest.approx(19.7)

    # Evidence records the URL (never the raw page), with no global cache row.
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).one()
    assert evidence.source_type == OFFICIAL_SOURCE_TYPE
    assert evidence.source_ref == f"official_source:{_BIG_MAC_URL}"
    assert evidence.product_id is None
    assert evidence.calories_per_100g == 250.0
    assert evidence.content_hash
    assert evidence.assumptions is None
    # No global products row is written for an official-source page.
    assert session.scalars(select(Product)).all() == []

    # The chain went search → fetch (item identity only; no personal context).
    assert search.queries == ["Big Mac McDonald's"]
    assert fetcher.fetched == [_BIG_MAC_URL]


def test_generic_miss_clarifies_without_official_search(
    client: TestClient, session: Session
) -> None:
    # A generic (unbranded) food USDA cannot resolve still clarifies — the official
    # step runs only for branded candidates, so search is never consulted.
    user_id, event_id = _seed_event(client, "official-generic@example.com", "some zorblax")
    search = FakeSearchProvider(_success_result())
    fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item={
            "type": "food",
            "name": "zorblax",
            "quantity_text": "150g",
            "unit": "g",
            "amount": 150,
        },
        search_provider=search,
        fetcher=fetcher,
        estimate={"disposition": "resolved", "confidence": 0.9, "facts": _PAGE_FACTS},
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION
    assert _foods(session, event_id) == []
    assert search.queries == []  # official source never consulted for a generic food
    assert fetcher.fetched == []


def test_branded_food_resolved_by_usda_skips_official(client: TestClient, session: Session) -> None:
    # When USDA resolves a branded item, the official step is the *last* resort and is
    # never consulted (only after a USDA/OFF miss).
    user_id, event_id = _seed_event(client, "official-usda@example.com", "a Big Mac")
    facts = ProductFacts(
        source=FDC_SOURCE,
        source_ref="usda_fdc:1",
        query_key="big mac",
        description="Big Mac",
        facts=NutritionFacts(calories=250.0, protein_g=10.0, carbs_g=30.0, fat_g=9.0),
        default_serving_g=219.0,
        content_hash="bigmachash",
    )
    search = FakeSearchProvider(_success_result())
    fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({"big mac": facts}),
        parsed_item=_branded_item(),
        search_provider=search,
        fetcher=fetcher,
        estimate={"disposition": "resolved", "confidence": 0.9, "facts": _PAGE_FACTS},
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).one()
    assert evidence.source_type == "trusted_nutrition_database"
    assert search.queries == []  # USDA resolved it; official source not consulted
    assert fetcher.fetched == []


def test_disabled_provider_falls_through_to_model_prior(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "official-modelprior@example.com", "a Big Mac")
    search = FakeSearchProvider(_success_result(), enabled=False)  # provider turned off
    fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item=_branded_item(),
        search_provider=search,
        fetcher=fetcher,
        estimate={
            "disposition": "resolved",
            "confidence": 0.6,
            "facts": _PAGE_FACTS,
            "assumptions": ["assumed a standard recipe"],
        },
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    foods = _foods(session, event_id)
    assert len(foods) == 1
    assert foods[0].status == DerivedItemStatus.RESOLVED
    assert foods[0].calories == 547.5

    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).one()
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert evidence.source_ref == "model_prior"
    assert evidence.product_id is None
    # The explicit source status carries the reason it was used + the model's own.
    assert evidence.assumptions is not None
    assert any("disabled" in a for a in evidence.assumptions)
    assert "assumed a standard recipe" in evidence.assumptions

    # A disabled provider is never called, and nothing is fetched.
    assert search.queries == []
    assert fetcher.fetched == []


def test_no_direct_egress_uses_injected_search_and_fetch(
    client: TestClient, session: Session
) -> None:
    # The step proves it makes no direct network call: search goes through the FTY-079
    # adapter seam and fetch through the FTY-078 fetcher seam, with the fetched URL
    # coming straight from the search result.
    user_id, event_id = _seed_event(client, "official-egress@example.com", "a Big Mac")
    search = FakeSearchProvider(_success_result("https://example.com/p/bigmac"))
    fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item=_branded_item(),
        search_provider=search,
        fetcher=fetcher,
        estimate={"disposition": "resolved", "confidence": 0.9, "facts": _PAGE_FACTS},
    )

    process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert search.queries == ["Big Mac McDonald's"]
    # The fetcher only ever sees a URL the search adapter returned.
    assert fetcher.fetched == ["https://example.com/p/bigmac"]


def test_low_confidence_extraction_falls_through_to_model_prior(
    client: TestClient, session: Session
) -> None:
    # A shaky page scrape (below the confidence threshold) is not trusted; the resolver
    # falls through to a model-prior estimate rather than persist an uncertain number.
    user_id, event_id = _seed_event(client, "official-lowconf@example.com", "a Big Mac")
    search = FakeSearchProvider(_success_result())
    fetcher = RecordingFetcher()
    parse_provider = FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": [_branded_item()]}]
    )
    # First extraction reply is low-confidence (rejected); then a model-prior estimate.
    official_provider = FakeProvider(
        responses=[
            {"disposition": "resolved", "confidence": 0.2, "facts": _PAGE_FACTS},
            {
                "disposition": "resolved",
                "confidence": 0.6,
                "facts": _PAGE_FACTS,
                "assumptions": ["model prior"],
            },
        ]
    )
    resolver = FoodResolver(session=session, source=FakeFoodSource({}))
    official_step = OfficialSourceResolveStep(
        provider=official_provider,
        search_provider=search,
        fetch_settings=_fetch_settings(),
        fetch_fn=fetcher,
    )
    pipeline = Pipeline([ParseStep(parse_provider), FoodResolveStep(resolver), official_step])

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).one()
    # The page was fetched and extracted, but the low-confidence reply was not trusted.
    assert fetcher.fetched == [_BIG_MAC_URL]
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
