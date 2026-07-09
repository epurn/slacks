"""End-to-end tests for the official/reference-source resolution step (FTY-062/166).

Drive :func:`app.estimator.processing.process_estimation` with the real
:class:`ParseStep` + :class:`FoodResolveStep` + :class:`OfficialSourceResolveStep`
(parse/extraction backed by the network-free :class:`FakeProvider`, search by a
scripted fake adapter, fetches by network-free fake fetchers) against the migrated
SQLite database, proving the acceptance criteria across the trust boundary:

- a branded product USDA/OFF cannot resolve is costed from an official page
  (search → fetch → extract → schema-validate → serving math) into a ``resolved``
  ``derived_food_items`` row plus an ``evidence_sources`` row carrying
  ``official_source:<url>``, a content hash, and the per-100g snapshot — never a raw
  page, and with no ``product_id``;
- the tier order is explicit (FTY-166): a branded item tries official source, then
  reference source, then model prior; a detail-rich generic item (FTY-167) skips the
  official search (no brand page exists) and tries reference source, then model
  prior;
- a detail-rich generic food USDA cannot resolve is costed from a stubbed public
  reference page with ``source_type = reference_source`` and deterministic
  calories/macros — the model prior is not consulted;
- when reference search/fetch/extraction fails, the model prior is used only with
  explicit assumptions naming why each evidence tier produced nothing — never a
  silent guess;
- the step issues no direct egress: search flows through the injected adapter and
  fetches through the injected hardened fetchers.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

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
from app.estimator.official_step import OfficialSourceResolveStep
from app.estimator.parse import ParseStep
from app.estimator.pipeline import Pipeline
from app.estimator.processing import process_estimation
from app.estimator.reference_fetch import ReferenceFetchSettings
from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    SearchCandidate,
    SearchCapability,
    SearchResult,
    SearchStatus,
)
from app.estimator.searched_reference import MODEL_PRIOR_SOURCE_TYPE, REFERENCE_SOURCE_TYPE
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource, Product

_BIG_MAC_URL = "https://example.com/menu/big-mac"
_REFERENCE_URL = "https://nutrition-reference.example.com/foods/gruel"

#: A sentinel embedded in every fake fetched page, asserted absent from everything
#: persisted — raw page text must never be retained.
_RAW_PAGE_SENTINEL = "RAW-PAGE-SENTINEL"

# Canonical per-100g facts the fetched page / model prior "reports", chosen for exact
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

# Reference-page facts for a generic food: 60 kcal / 2 P / 11 C / 1 F per 100 g.
_REFERENCE_FACTS = {
    "basis": "per_100g",
    "product_name": "gruel",
    "calories": 60.0,
    "protein_g": 2.0,
    "carbs_g": 11.0,
    "fat_g": 1.0,
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
    """A network-free page fetcher recording the URLs it is handed.

    Stands in for both the official (FTY-078) and searched-result (FTY-166) fetch
    seams — the step only calls it with ``(url, settings)``.
    """

    def __init__(self, text: str = f"Big Mac — 250 kcal per 100 g {_RAW_PAGE_SENTINEL}") -> None:
        self._text = text
        self.fetched: list[str] = []

    def __call__(self, url: str, settings: object) -> str:
        self.fetched.append(url)
        return self._text


def _success_result(url: str = _BIG_MAC_URL) -> SearchResult:
    return SearchResult(
        status=SearchStatus.SUCCESS,
        candidates=(SearchCandidate(url=url, title="Big Mac | McDonald's"),),
    )


def _no_result() -> SearchResult:
    return SearchResult(status=SearchStatus.PARTIAL)


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
    estimates: list[dict[str, Any] | LLMError],
    fetch_settings: OfficialFetchSettings | None = None,
    reference_fetcher: RecordingFetcher | None = None,
    reference_settings: ReferenceFetchSettings | None = None,
) -> Pipeline:
    """Real parse + food + official/reference pipeline with all network seams faked."""

    parse_provider = FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": [parsed_item]}]
        * SELF_CONSISTENCY_FIRST_WINDOW
    )
    official_provider = FakeProvider(responses=estimates)
    resolver = FoodResolver(session=session, source=food_source)
    official_step = OfficialSourceResolveStep(
        provider=official_provider,
        search_provider=search_provider,
        fetch_settings=fetch_settings or _fetch_settings(),
        reference_fetch_settings=reference_settings or ReferenceFetchSettings(),
        fetch_fn=fetcher,
        reference_fetch_fn=reference_fetcher or fetcher,
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


def _evidence(session: Session, event_id: uuid.UUID) -> EvidenceSource:
    return session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).one()


def _branded_item() -> dict[str, object]:
    return {
        "type": "food",
        "name": "Big Mac",
        "brand": "McDonald's",
        "quantity_text": "1",
        "amount": 1,
    }


def _generic_item() -> dict[str, object]:
    return {
        "type": "food",
        "name": "gruel",
        "quantity_text": "150g",
        "unit": "g",
        "amount": 150,
    }


def test_branded_food_resolves_from_official_source(client: TestClient, session: Session) -> None:
    user_id, event_id = _seed_event(client, "official-ok@example.com", "a Big Mac")
    search = FakeSearchProvider(_success_result())
    fetcher = RecordingFetcher()
    reference_fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),  # USDA miss
        parsed_item=_branded_item(),
        search_provider=search,
        fetcher=fetcher,
        reference_fetcher=reference_fetcher,
        estimates=[{"disposition": "resolved", "confidence": 0.9, "facts": _PAGE_FACTS}],
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
    evidence = _evidence(session, event_id)
    assert evidence.source_type == OFFICIAL_SOURCE_TYPE
    assert evidence.source_ref == f"official_source:{_BIG_MAC_URL}"
    assert evidence.product_id is None
    assert evidence.calories_per_100g == 250.0
    assert evidence.content_hash
    assert evidence.assumptions is None
    # No global products row is written for an official-source page.
    assert session.scalars(select(Product)).all() == []

    # The chain went search → fetch (item identity only; no personal context), and
    # the official page satisfied it — the reference tier was never consulted.
    assert search.queries == ["Big Mac McDonald's"]
    assert fetcher.fetched == [_BIG_MAC_URL]
    assert reference_fetcher.fetched == []


# --- reference-source tier (FTY-166) ----------------------------------------------


def test_detailed_generic_resolves_from_reference_source(
    client: TestClient, session: Session
) -> None:
    # FTY-166 acceptance: a detail-rich generic food USDA cannot resolve is costed
    # from a public reference page — search (identity + fixed nutrition intent) →
    # searched-result fetch → extract → serving math — with
    # source_type=reference_source. Official search is skipped (no brand page) and
    # the model prior is never consulted.
    user_id, event_id = _seed_event(client, "reference-generic@example.com", "150g of gruel")
    search = FakeSearchProvider(_success_result(_REFERENCE_URL))
    fetcher = RecordingFetcher()
    reference_fetcher = RecordingFetcher(text=f"Gruel — 60 kcal per 100 g {_RAW_PAGE_SENTINEL}")
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),  # USDA miss
        parsed_item=_generic_item(),
        search_provider=search,
        fetcher=fetcher,
        reference_fetcher=reference_fetcher,
        estimates=[{"disposition": "resolved", "confidence": 0.9, "facts": _REFERENCE_FACTS}],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED

    foods = _foods(session, event_id)
    assert len(foods) == 1
    food = foods[0]
    assert food.status == DerivedItemStatus.RESOLVED
    # Deterministic math: 150 g of 60 kcal / 2 P / 11 C / 1 F per-100g.
    assert food.grams == 150.0
    assert food.calories == 90.0
    assert food.protein_g == pytest.approx(3.0)
    assert food.carbs_g == pytest.approx(16.5)
    assert food.fat_g == pytest.approx(1.5)

    # Provenance distinguishes the reference tier; the URL only, no global cache row.
    evidence = _evidence(session, event_id)
    assert evidence.source_type == REFERENCE_SOURCE_TYPE
    assert evidence.source_ref == f"reference_source:{_REFERENCE_URL}"
    assert evidence.product_id is None
    assert evidence.calories_per_100g == 60.0
    assert evidence.content_hash
    assert session.scalars(select(Product)).all() == []

    # The only search that egressed is the sanitized identity + the fixed nutrition
    # intent; the official fetcher was never used for a generic food.
    assert search.queries == ["gruel nutrition facts"]
    assert fetcher.fetched == []
    assert reference_fetcher.fetched == [_REFERENCE_URL]


def test_branded_official_miss_resolves_from_reference_before_model_prior(
    client: TestClient, session: Session
) -> None:
    # FTY-166 acceptance: the branded order is official → reference → model prior.
    # The official page yields no usable facts; the reference page resolves, so the
    # model prior is never consulted.
    user_id, event_id = _seed_event(client, "reference-branded@example.com", "a Big Mac")
    search = FakeSearchProvider(_success_result())
    fetcher = RecordingFetcher()
    reference_fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item=_branded_item(),
        search_provider=search,
        fetcher=fetcher,
        reference_fetcher=reference_fetcher,
        estimates=[
            # Official-page extraction finds nothing usable on the page.
            {"disposition": "unresolved", "confidence": 0.9},
            # Reference-page extraction states the facts.
            {"disposition": "resolved", "confidence": 0.9, "facts": _PAGE_FACTS},
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    evidence = _evidence(session, event_id)
    assert evidence.source_type == REFERENCE_SOURCE_TYPE
    assert evidence.source_ref == f"reference_source:{_BIG_MAC_URL}"

    # Explicit tier order: the official search (identity) ran first, then the
    # reference search (identity + nutrition intent); each tier fetched through its
    # own injected fetcher.
    assert search.queries == ["Big Mac McDonald's", "Big Mac McDonald's nutrition facts"]
    assert fetcher.fetched == [_BIG_MAC_URL]
    assert reference_fetcher.fetched == [_BIG_MAC_URL]


def test_reference_miss_falls_through_to_model_prior_with_explicit_status(
    client: TestClient, session: Session
) -> None:
    # FTY-166 acceptance: when reference search yields nothing, the model prior is
    # used only with explicit assumptions naming why each evidence tier produced
    # nothing (FTY-167 detail-rich generic shown here).
    user_id, event_id = _seed_event(client, "reference-miss@example.com", "150g of gruel")
    search = FakeSearchProvider(_no_result())  # search answers but offers no URL
    fetcher = RecordingFetcher()
    reference_fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item=_generic_item(),
        search_provider=search,
        fetcher=fetcher,
        reference_fetcher=reference_fetcher,
        estimates=[{"disposition": "resolved", "confidence": 0.9, "facts": _PAGE_FACTS}],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED

    foods = _foods(session, event_id)
    assert len(foods) == 1
    assert foods[0].status == DerivedItemStatus.RESOLVED
    # 150 g of 250 kcal/100 g per the model-prior facts.
    assert foods[0].calories == 375.0

    evidence = _evidence(session, event_id)
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert evidence.source_ref == "model_prior"
    # The explicit source status names, per tier, why no evidence was used.
    assert evidence.assumptions is not None
    reason = next(a for a in evidence.assumptions if "model prior" in a)
    assert "generic food" in reason
    assert "reference_source returned no confident match" in reason

    # Reference search ran (identity + intent); nothing came back to fetch.
    assert search.queries == ["gruel nutrition facts"]
    assert fetcher.fetched == []
    assert reference_fetcher.fetched == []


def test_reference_fetch_disabled_falls_through_to_model_prior(
    client: TestClient, session: Session
) -> None:
    # With searched-result fetch explicitly off, the reference tier is skipped
    # without any search/fetch, and the model-prior status says so.
    user_id, event_id = _seed_event(client, "reference-off@example.com", "150g of gruel")
    search = FakeSearchProvider(_success_result(_REFERENCE_URL))
    fetcher = RecordingFetcher()
    reference_fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item=_generic_item(),
        search_provider=search,
        fetcher=fetcher,
        reference_fetcher=reference_fetcher,
        reference_settings=ReferenceFetchSettings(enabled=False),
        estimates=[{"disposition": "resolved", "confidence": 0.9, "facts": _PAGE_FACTS}],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    evidence = _evidence(session, event_id)
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert evidence.assumptions is not None
    reason = next(a for a in evidence.assumptions if "model prior" in a)
    assert "reference_source fetch disabled" in reason

    # The disabled tier never searched or fetched anything.
    assert search.queries == []
    assert fetcher.fetched == []
    assert reference_fetcher.fetched == []


def test_no_raw_page_text_is_persisted(client: TestClient, session: Session) -> None:
    # FTY-166 acceptance: evidence persistence stores provenance and extracted facts,
    # never raw page text. The fetched page carries a sentinel; after resolution the
    # sentinel appears nowhere in any persisted row.
    user_id, event_id = _seed_event(client, "reference-raw@example.com", "150g of gruel")
    reference_fetcher = RecordingFetcher(text=f"Gruel — 60 kcal per 100 g {_RAW_PAGE_SENTINEL}")
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item=_generic_item(),
        search_provider=FakeSearchProvider(_success_result(_REFERENCE_URL)),
        fetcher=RecordingFetcher(),
        reference_fetcher=reference_fetcher,
        estimates=[{"disposition": "resolved", "confidence": 0.9, "facts": _REFERENCE_FACTS}],
    )

    process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    evidence = _evidence(session, event_id)
    persisted_columns = {
        column.key: getattr(evidence, column.key) for column in evidence.__table__.columns
    }
    assert _RAW_PAGE_SENTINEL not in repr(persisted_columns)
    food = _foods(session, event_id)[0]
    food_columns = {column.key: getattr(food, column.key) for column in food.__table__.columns}
    assert _RAW_PAGE_SENTINEL not in repr(food_columns)


# --- FTY-167 generic routing (updated for the reference tier) -----------------------


def test_amountless_generic_miss_resolves_from_reference_source(
    client: TestClient, session: Session
) -> None:
    # FTY-301: under the default estimate-first policy, a recognizable generic food
    # with no explicit amount falls forward to rough reference/model/default serving
    # estimation instead of the generic quantity question.
    user_id, event_id = _seed_event(client, "official-vague@example.com", "some crackers")
    search = FakeSearchProvider(_success_result())
    fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item={"type": "food", "name": "crackers"},  # no amount / count / range
        search_provider=search,
        fetcher=fetcher,
        estimates=[{"disposition": "resolved", "confidence": 0.9, "facts": _PAGE_FACTS}],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    foods = _foods(session, event_id)
    assert len(foods) == 1
    assert foods[0].status == DerivedItemStatus.RESOLVED
    evidence = _evidence(session, event_id)
    assert evidence.source_type == REFERENCE_SOURCE_TYPE
    assert evidence.assumptions is not None
    assert "estimated_default_serving" in evidence.assumptions
    assert search.queries == ["crackers nutrition facts"]
    assert fetcher.fetched == [_BIG_MAC_URL]


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
        estimates=[{"disposition": "resolved", "confidence": 0.9, "facts": _PAGE_FACTS}],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    evidence = _evidence(session, event_id)
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
        estimates=[
            {
                "disposition": "resolved",
                "confidence": 0.6,
                "facts": _PAGE_FACTS,
                "assumptions": ["assumed a standard recipe"],
            }
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    foods = _foods(session, event_id)
    assert len(foods) == 1
    assert foods[0].status == DerivedItemStatus.RESOLVED
    assert foods[0].calories == 547.5

    evidence = _evidence(session, event_id)
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert evidence.source_ref == "model_prior"
    assert evidence.product_id is None
    # The explicit source status carries the per-tier reason plus the model's own.
    assert evidence.assumptions is not None
    reason = next(a for a in evidence.assumptions if "model prior" in a)
    assert "official_source search disabled" in reason
    assert "reference_source search disabled" in reason
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
    reference_fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item=_branded_item(),
        search_provider=search,
        fetcher=fetcher,
        reference_fetcher=reference_fetcher,
        estimates=[{"disposition": "resolved", "confidence": 0.9, "facts": _PAGE_FACTS}],
    )

    process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert search.queries == ["Big Mac McDonald's"]
    # Each fetcher only ever sees a URL the search adapter returned.
    assert fetcher.fetched == ["https://example.com/p/bigmac"]
    assert reference_fetcher.fetched == []


def test_low_confidence_extractions_fall_through_to_model_prior(
    client: TestClient, session: Session
) -> None:
    # Shaky page scrapes (below the confidence threshold) are not trusted on either
    # evidence tier; the resolver falls through official → reference → model prior
    # rather than persist an uncertain number.
    user_id, event_id = _seed_event(client, "official-lowconf@example.com", "a Big Mac")
    search = FakeSearchProvider(_success_result())
    fetcher = RecordingFetcher()
    reference_fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item=_branded_item(),
        search_provider=search,
        fetcher=fetcher,
        reference_fetcher=reference_fetcher,
        estimates=[
            # Official-page extraction: low confidence, rejected.
            {"disposition": "resolved", "confidence": 0.2, "facts": _PAGE_FACTS},
            # Reference-page extraction: low confidence, rejected.
            {"disposition": "resolved", "confidence": 0.2, "facts": _PAGE_FACTS},
            # Model-prior estimate: trusted, with its explicit status.
            {
                "disposition": "resolved",
                "confidence": 0.6,
                "facts": _PAGE_FACTS,
                "assumptions": ["model prior"],
            },
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    evidence = _evidence(session, event_id)
    # Both pages were fetched and extracted, but neither low-confidence reply was
    # trusted; the model prior carries the two-tier miss in its status.
    assert fetcher.fetched == [_BIG_MAC_URL]
    assert reference_fetcher.fetched == [_BIG_MAC_URL]
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert evidence.assumptions is not None
    reason = next(a for a in evidence.assumptions if "model prior" in a)
    assert "official_source returned no confident match" in reason
    assert "reference_source returned no confident match" in reason


# --- Plausibility-gate tests (FTY-132) ------------------------------------------


def test_page_kj_mislabelled_as_kcal_falls_through_to_model_prior(
    client: TestClient, session: Session
) -> None:
    # A page reporting ~3700 kcal/100g (kJ value mislabelled as kcal, comfortably under
    # the 10,000 schema ceiling) fails the physical-plausibility gate in _to_per_100g on
    # both evidence tiers; the resolver falls through to model-prior and commits nothing
    # for the bad pages.
    user_id, event_id = _seed_event(client, "official-inflated@example.com", "a Big Mac")
    search = FakeSearchProvider(_success_result())
    fetcher = RecordingFetcher()
    reference_fetcher = RecordingFetcher()
    inflated_facts = {
        "basis": "per_100g",
        "calories": 3700.0,  # kJ mislabelled as kcal; under 10,000 but > 900 kcal/100g
        "protein_g": 10.0,
        "carbs_g": 30.0,
        "fat_g": 9.0,
        "serving_size_amount": 219.0,
        "serving_size_unit": "g",
    }
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item=_branded_item(),
        search_provider=search,
        fetcher=fetcher,
        reference_fetcher=reference_fetcher,
        estimates=[
            # Official page: implausible, gate returns None → falls through.
            {"disposition": "resolved", "confidence": 0.9, "facts": inflated_facts},
            # Reference page: same implausible facts → falls through.
            {"disposition": "resolved", "confidence": 0.9, "facts": inflated_facts},
            # Model-prior estimate: plausible, resolves.
            {
                "disposition": "resolved",
                "confidence": 0.7,
                "facts": _PAGE_FACTS,
                "assumptions": ["estimated from model prior"],
            },
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    foods = _foods(session, event_id)
    assert len(foods) == 1
    # The resolved item uses model-prior facts (plausible 250 kcal/100g × 219g = 547.5),
    # not the inflated page facts.
    assert foods[0].calories == 547.5
    evidence = _evidence(session, event_id)
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    # Both pages were fetched but their inflated facts were rejected.
    assert fetcher.fetched == [_BIG_MAC_URL]
    assert reference_fetcher.fetched == [_BIG_MAC_URL]


def test_implausible_model_prior_routes_to_needs_clarification(
    client: TestClient, session: Session
) -> None:
    # When the model-prior estimate itself has implausible per-100g facts, the resolver
    # has no fallback and routes to needs_clarification rather than storing an absurd total.
    user_id, event_id = _seed_event(client, "official-mpimplaus@example.com", "a Big Mac")
    implausible_facts = {
        "basis": "per_100g",
        "calories": 3700.0,  # implausible; gate rejects → _build_item returns None
        "protein_g": 10.0,
        "carbs_g": 30.0,
        "fat_g": 9.0,
        "serving_size_amount": 219.0,
        "serving_size_unit": "g",
    }
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item=_branded_item(),
        # Search disabled → both evidence tiers skip; falls directly to model-prior.
        search_provider=FakeSearchProvider(_success_result(), enabled=False),
        fetcher=RecordingFetcher(),
        estimates=[{"disposition": "resolved", "confidence": 0.7, "facts": implausible_facts}],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION
    assert _foods(session, event_id) == []


def test_per_serving_implausible_per_100g_falls_through_to_model_prior(
    client: TestClient, session: Session
) -> None:
    # A page reporting per-serving facts that are plausible per serving but yield an
    # implausible per-100g after conversion fails the gate (gate is in canonical space).
    # Example: 95 kcal per 10 g serving → 950 kcal/100g, above the 900 kcal/100g ceiling.
    user_id, event_id = _seed_event(client, "official-persvg@example.com", "a Big Mac")
    search = FakeSearchProvider(_success_result())
    fetcher = RecordingFetcher()
    reference_fetcher = RecordingFetcher()
    implausible_per_serving_facts = {
        "basis": "per_serving",
        "calories": 95.0,  # plausible per-serving, but 10 g → 950 kcal/100g (implausible)
        "protein_g": 1.0,
        "carbs_g": 2.0,
        "fat_g": 0.5,
        "serving_size_amount": 10.0,
        "serving_size_unit": "g",
    }
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item=_branded_item(),
        search_provider=search,
        fetcher=fetcher,
        reference_fetcher=reference_fetcher,
        estimates=[
            # Official page: implausible per-100g → falls through.
            {"disposition": "resolved", "confidence": 0.9, "facts": implausible_per_serving_facts},
            # Reference page: same → falls through.
            {"disposition": "resolved", "confidence": 0.9, "facts": implausible_per_serving_facts},
            # Model-prior estimate: plausible, resolves.
            {
                "disposition": "resolved",
                "confidence": 0.7,
                "facts": _PAGE_FACTS,
                "assumptions": ["estimated from model prior"],
            },
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    evidence = _evidence(session, event_id)
    # Per-serving page facts were rejected after per-100g conversion on both tiers;
    # model-prior was used.
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert fetcher.fetched == [_BIG_MAC_URL]
    assert reference_fetcher.fetched == [_BIG_MAC_URL]


def test_zero_calorie_food_resolves_successfully(client: TestClient, session: Session) -> None:
    # A genuine zero-calorie food (e.g. black coffee) must not be blocked by the gate:
    # energy = 0 is valid and nutrition_facts_plausible allows it explicitly.
    user_id, event_id = _seed_event(client, "official-zerocal@example.com", "a Big Mac")
    zero_cal_facts = {
        "basis": "per_100g",
        "product_name": "Zero Cal Food",
        "calories": 0.0,
        "protein_g": 0.0,
        "carbs_g": 0.0,
        "fat_g": 0.0,
        "serving_size_amount": 219.0,
        "serving_size_unit": "g",
    }
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item=_branded_item(),
        search_provider=FakeSearchProvider(_success_result()),
        fetcher=RecordingFetcher(),
        estimates=[{"disposition": "resolved", "confidence": 0.9, "facts": zero_cal_facts}],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    foods = _foods(session, event_id)
    assert len(foods) == 1
    assert foods[0].calories == 0.0
    evidence = _evidence(session, event_id)
    assert evidence.source_type == OFFICIAL_SOURCE_TYPE
