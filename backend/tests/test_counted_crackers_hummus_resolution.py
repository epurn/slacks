"""FTY-292 regression tests for counted crackers plus measured hummus.

These drive the real parse -> food-resolution -> official/reference/model-prior
pipeline with network-free fakes. The load-bearing behavior is that a cracker
count plus a household-volume spread amount resolves as intake, even when exact
product/reference lookup misses, and after FTY-301 amountless recognized snacks rough
estimate instead of clarifying.
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
from app.estimator.fdc import ProductFacts
from app.estimator.food_resolvers import FoodResolver
from app.estimator.food_step import FoodResolveStep
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
from app.estimator.searched_reference import MODEL_PRIOR_SOURCE_TYPE
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider
from app.models.derived import ClarificationQuestion, DerivedFoodItem
from app.models.estimation import EstimationRun
from app.models.food_sources import EvidenceSource, Product

_REFERENCE_URL = "https://nutrition-reference.example.com/foods/snack"
_CRACKER_VARIANT = "6 crackers with about 1.5-2 tbsp dill pickle hummus"
_BRANDED_VARIANT = "6 Toppables-style crackers plus roughly 1.75 tbsp Loblaws-style dill hummus"

_CRACKER_MODEL_PRIOR_FACTS = {
    "basis": "per_100g",
    "product_name": "plain crackers",
    "calories": 430.0,
    "protein_g": 9.0,
    "carbs_g": 70.0,
    "fat_g": 12.0,
    "serving_size_amount": 3.0,
    "serving_size_unit": "g",
}

_HUMMUS_MODEL_PRIOR_FACTS = {
    "basis": "per_100g",
    "product_name": "dill pickle hummus",
    "calories": 170.0,
    "protein_g": 7.0,
    "carbs_g": 14.0,
    "fat_g": 10.0,
    "serving_size_amount": 30.0,
    "serving_size_unit": "g",
}


class FakeFoodSource:
    """A network-free USDA stand-in that intentionally misses these products."""

    @property
    def enabled(self) -> bool:
        return True

    def lookup(self, query: str) -> ProductFacts | None:
        return None


class FakeSearchProvider:
    """A network-free search seam that records sanitized identity queries."""

    def __init__(self, result: SearchResult) -> None:
        self._result = result
        self.queries: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    @property
    def available(self) -> bool:
        return True

    @property
    def capability(self) -> SearchCapability:
        return SearchCapability(
            id="official_source",
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=("named_product", "restaurant_item"),
            enabled=True,
            available=True,
        )

    def search(self, query: str) -> SearchResult:
        self.queries.append(query)
        return self._result


class RecordingFetcher:
    """A network-free fetch seam; the FTY-292 source-miss path should not fetch."""

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def __call__(self, url: str, settings: object) -> str:
        self.fetched.append(url)
        return "unused fetched page"


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _no_result() -> SearchResult:
    return SearchResult(status=SearchStatus.PARTIAL)


def _success_result() -> SearchResult:
    return SearchResult(
        status=SearchStatus.SUCCESS,
        candidates=(SearchCandidate(url=_REFERENCE_URL, title="snack nutrition"),),
    )


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


def _pipeline(
    session: Session,
    *,
    parsed_items: list[dict[str, object]],
    estimates: list[dict[str, Any] | LLMError],
    search: FakeSearchProvider,
    fetcher: RecordingFetcher,
    reference_fetcher: RecordingFetcher | None = None,
) -> Pipeline:
    parse_provider = FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": parsed_items}]
        * SELF_CONSISTENCY_FIRST_WINDOW
    )
    resolver = FoodResolver(session=session, source=FakeFoodSource())
    official_step = OfficialSourceResolveStep(
        provider=FakeProvider(responses=estimates),
        search_provider=search,
        fetch_settings=OfficialFetchSettings(allowed_hosts=frozenset({"example.com"})),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=fetcher,
        reference_fetch_fn=reference_fetcher or fetcher,
    )
    return Pipeline([ParseStep(parse_provider), FoodResolveStep(resolver), official_step])


def _cracker_and_hummus_items() -> list[dict[str, object]]:
    return [
        {
            "type": "food",
            "name": "crackers",
            "brand": "Toppables-style",
            "quantity_text": "6",
            "unit": "crackers",
            "amount": 6,
        },
        {
            "type": "food",
            "name": "dill pickle hummus",
            "brand": "Loblaws-style",
            "quantity_text": "about 1.5-2 tbsp",
            "unit": "tbsp",
            "amount": 1.75,
        },
    ]


def _foods(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    )


def _evidence(session: Session, event_id: uuid.UUID) -> list[EvidenceSource]:
    return list(
        session.scalars(select(EvidenceSource).where(EvidenceSource.log_event_id == event_id))
    )


def _run(session: Session, event_id: uuid.UUID) -> EstimationRun:
    return session.scalars(
        select(EstimationRun).where(EstimationRun.log_event_id == event_id)
    ).one()


def _questions(session: Session, event_id: uuid.UUID) -> list[ClarificationQuestion]:
    return list(
        session.scalars(
            select(ClarificationQuestion).where(ClarificationQuestion.log_event_id == event_id)
        )
    )


def test_counted_crackers_and_measured_hummus_resolve_after_exact_source_miss(
    client: TestClient, session: Session
) -> None:
    search = FakeSearchProvider(_no_result())
    fetcher = RecordingFetcher()
    reference_fetcher = RecordingFetcher()
    user_id, event_id = _seed_event(client, "fty292-generic@example.com", _CRACKER_VARIANT)
    pipeline = _pipeline(
        session,
        parsed_items=_cracker_and_hummus_items(),
        search=search,
        fetcher=fetcher,
        reference_fetcher=reference_fetcher,
        estimates=[
            {
                "disposition": "resolved",
                "confidence": 0.7,
                "facts": _CRACKER_MODEL_PRIOR_FACTS,
                "assumptions": ["typical plain cracker"],
            },
            {
                "disposition": "resolved",
                "confidence": 0.7,
                "facts": _HUMMUS_MODEL_PRIOR_FACTS,
                "assumptions": ["typical prepared hummus"],
            },
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    foods = sorted(_foods(session, event_id), key=lambda row: row.name)
    assert [food.name for food in foods] == ["crackers", "dill pickle hummus"]
    crackers, hummus = foods
    assert all(food.status == DerivedItemStatus.RESOLVED for food in foods)
    assert crackers.grams == 18.0
    assert crackers.calories == 77.4
    assert crackers.protein_g == pytest.approx(1.6)
    assert crackers.carbs_g == pytest.approx(12.6)
    assert crackers.fat_g == pytest.approx(2.2)
    assert hummus.grams == 26.25
    assert hummus.calories == 44.6
    assert hummus.protein_g == pytest.approx(1.8)
    assert hummus.carbs_g == pytest.approx(3.7)
    assert hummus.fat_g == pytest.approx(2.6)

    evidence = _evidence(session, event_id)
    assert len(evidence) == 2
    assert {row.source_type for row in evidence} == {MODEL_PRIOR_SOURCE_TYPE}
    assert {row.source_ref for row in evidence} == {"model_prior"}
    assert all(row.product_id is None for row in evidence)
    assert session.scalars(select(Product)).all() == []
    assert search.queries == [
        "crackers Toppables-style",
        "crackers Toppables-style nutrition facts",
        "dill pickle hummus Loblaws-style",
        "dill pickle hummus Loblaws-style nutrition facts",
    ]
    assert fetcher.fetched == []
    assert reference_fetcher.fetched == []

    run = _run(session, event_id)
    persisted = (
        f"{run.trace!r} {run.assumptions!r} {run.source_refs!r} "
        f"{run.validation_errors!r} {run.error!r}"
    )
    assert _CRACKER_VARIANT not in persisted
    assert "How much did you have" not in persisted
    assert not any("How much did you have" in str(row.assumptions) for row in evidence)


def test_branded_counted_crackers_and_measured_hummus_variant_resolves(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "fty292-branded@example.com", _BRANDED_VARIANT)
    pipeline = _pipeline(
        session,
        parsed_items=_cracker_and_hummus_items(),
        search=FakeSearchProvider(_no_result()),
        fetcher=RecordingFetcher(),
        estimates=[
            {"disposition": "resolved", "confidence": 0.7, "facts": _CRACKER_MODEL_PRIOR_FACTS},
            {"disposition": "resolved", "confidence": 0.7, "facts": _HUMMUS_MODEL_PRIOR_FACTS},
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    foods = _foods(session, event_id)
    assert len(foods) == 2
    assert {food.status for food in foods} == {DerivedItemStatus.RESOLVED}
    assert all(food.calories is not None for food in foods)


def test_amountless_crackers_and_hummus_rough_estimates(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "fty292-amountless@example.com", "crackers and hummus")
    search = FakeSearchProvider(_no_result())
    fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        parsed_items=[
            {"type": "food", "name": "crackers"},
            {"type": "food", "name": "hummus"},
        ],
        search=search,
        fetcher=fetcher,
        estimates=[
            {"disposition": "resolved", "confidence": 0.9, "facts": _CRACKER_MODEL_PRIOR_FACTS},
            {"disposition": "resolved", "confidence": 0.9, "facts": _HUMMUS_MODEL_PRIOR_FACTS},
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    foods = _foods(session, event_id)
    assert len(foods) == 2
    assert {food.status for food in foods} == {DerivedItemStatus.RESOLVED}
    assert {row.source_type for row in _evidence(session, event_id)} == {MODEL_PRIOR_SOURCE_TYPE}
    assert search.queries == ["crackers nutrition facts", "hummus nutrition facts"]
    assert fetcher.fetched == []
