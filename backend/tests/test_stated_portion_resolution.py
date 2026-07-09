"""End-to-end tests for stated worded/household-portion resolution (FTY-275).

Drive :func:`app.estimator.processing.process_estimation` with the real
:class:`ParseStep` + :class:`FoodResolveStep` + :class:`OfficialSourceResolveStep`
(all network seams faked) against the migrated database, proving the acceptance
criteria across the trust boundary:

- the dogfooding repro — "Robin Hood oatmeal (1/3 cup) with a splash of 1% milk and
  about a tsp of maple syrup" — resolves with every component costed (a numeric
  household measure, a colloquial measure, and an approximate household measure) and
  **no** ``needs_clarification`` / ``QUANTITY_QUESTION``: the household serving math
  (FTY-275) costs the cup / tsp / ml, oatmeal + milk from USDA and the (unmatched)
  syrup from a model-prior estimate;
- the fail-closed boundary is preserved: a genuinely amountless component can still
  route to ``needs_clarification`` when every rough estimator path is unavailable.

The deterministic serving math and the ``has_food_detail`` net are pinned separately
in ``test_food_serving.py`` and ``test_detail_signals.py``; this proves them wired
end-to-end through the pipeline.
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
from app.estimator.search import OFFICIAL_SOURCE_TYPE, SearchCapability, SearchResult, SearchStatus
from app.estimator.searched_reference import MODEL_PRIOR_SOURCE_TYPE
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource


class _FakeFoodSource:
    """A scripted, network-free generic-food source (USDA stand-in)."""

    def __init__(self, facts: dict[str, ProductFacts] | None = None) -> None:
        self._facts = facts or {}

    @property
    def enabled(self) -> bool:
        return True

    def lookup(self, query: str) -> ProductFacts | None:
        return self._facts.get(query.strip().lower())


class _DisabledSearchProvider:
    """A search provider that is off, so a generic miss falls straight to model prior."""

    @property
    def enabled(self) -> bool:
        return False

    @property
    def available(self) -> bool:
        return False

    @property
    def capability(self) -> SearchCapability:
        return SearchCapability(
            id="official_source",
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=("named_product",),
            enabled=False,
            available=False,
        )

    def search(self, query: str) -> SearchResult:  # pragma: no cover - never reached when off
        return SearchResult(status=SearchStatus.PARTIAL)


def _unused_fetch(url: str, settings: object) -> str:  # pragma: no cover - search is off
    raise AssertionError("fetch must not run when search is disabled")


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _facts(query_key: str, calories: float) -> ProductFacts:
    return ProductFacts(
        source=FDC_SOURCE,
        source_ref=f"usda_fdc:{query_key}",
        query_key=query_key,
        description=query_key,
        facts=NutritionFacts(calories=calories, protein_g=0.0, carbs_g=0.0, fat_g=0.0),
        default_serving_g=None,
        content_hash=f"{query_key}-hash",
    )


def _pipeline(
    session: Session,
    *,
    food_source: _FakeFoodSource,
    parsed_items: list[dict[str, Any]],
    estimates: list[dict[str, Any] | LLMError],
) -> Pipeline:
    """Full parse + food + official/model-prior pipeline for a multi-component log."""

    parse_provider = FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": parsed_items}]
        * SELF_CONSISTENCY_FIRST_WINDOW
    )
    resolver = FoodResolver(session=session, source=food_source)
    official_step = OfficialSourceResolveStep(
        provider=FakeProvider(responses=estimates),
        search_provider=_DisabledSearchProvider(),
        fetch_settings=OfficialFetchSettings(allowed_hosts=frozenset({"example.com"})),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=_unused_fetch,
        reference_fetch_fn=_unused_fetch,
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


def test_repro_household_and_worded_portions_resolve_without_clarification(
    client: TestClient, session: Session
) -> None:
    # The dogfooding repro (2026-07-07): every component states a portion — a numeric
    # household measure ("1/3 cup"), a colloquial measure ("a splash"), and an
    # approximate household measure ("about a tsp"). The parse resolves each to a
    # concrete amount+unit; the household serving math (FTY-275) costs the cup/tsp/ml,
    # oatmeal + milk from USDA and the (unmatched) syrup from a model-prior estimate.
    # The event completes with all three costed — no needs_clarification.
    user_id, event_id = _seed_event(
        client,
        "fty275-repro@example.com",
        "Robin Hood oatmeal (1/3 cup) with a splash of 1% milk and about a tsp of maple syrup",
    )
    parsed_items = [
        # "1/3 cup" → household cup unit; costs at 240 ml/cup → ~80 g.
        {
            "type": "food",
            "name": "Robin Hood oatmeal",
            "quantity_text": "1/3 cup",
            "unit": "cup",
            "amount": 1 / 3,
        },
        # "a splash of 1% milk" → the parse resolved the colloquial phrase to ~30 ml.
        {
            "type": "food",
            "name": "1% milk",
            "quantity_text": "a splash",
            "unit": "ml",
            "amount": 30,
        },
        # "about a tsp of maple syrup" → household tsp unit; costs at 5 ml/tsp → ~5 g.
        {
            "type": "food",
            "name": "maple syrup",
            "quantity_text": "about a tsp",
            "unit": "tsp",
            "amount": 1,
        },
    ]
    # USDA matches oatmeal and milk; maple syrup misses → deferred to model-prior.
    food_source = _FakeFoodSource(
        {
            "robin hood oatmeal": _facts("robin hood oatmeal", 380.0),
            "1% milk": _facts("1% milk", 42.0),
        }
    )
    syrup_estimate = {
        "disposition": "resolved",
        "confidence": 0.8,
        "facts": {
            "basis": "per_100g",
            "product_name": "maple syrup",
            "calories": 260.0,
            "protein_g": 0.0,
            "carbs_g": 67.0,
            "fat_g": 0.0,
        },
    }

    pipeline = _pipeline(
        session,
        food_source=food_source,
        parsed_items=parsed_items,
        estimates=[syrup_estimate],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    # No clarification: the event completes with every component costed.
    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED

    foods = {food.name: food for food in _foods(session, event_id)}
    assert set(foods) == {"Robin Hood oatmeal", "1% milk", "maple syrup"}
    assert all(food.status == DerivedItemStatus.RESOLVED for food in foods.values())

    # Household cup: 1/3 cup → 240 ml/cup ≈ 80 g; 380 kcal/100g → 304 kcal.
    oatmeal = foods["Robin Hood oatmeal"]
    assert oatmeal.grams == pytest.approx(80.0, abs=0.05)
    assert oatmeal.calories == pytest.approx(304.0, abs=0.2)

    # "a splash" resolved to 30 ml → 30 g; 42 kcal/100g → 12.6 kcal.
    milk = foods["1% milk"]
    assert milk.grams == pytest.approx(30.0)
    assert milk.calories == pytest.approx(12.6)

    # Household tsp: 1 tsp → 5 ml ≈ 5 g; costed from the model-prior estimate.
    syrup = foods["maple syrup"]
    assert syrup.grams == pytest.approx(5.0)
    assert syrup.calories == pytest.approx(13.0)
    syrup_evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == syrup.id)
    ).one()
    assert syrup_evidence.source_type == MODEL_PRIOR_SOURCE_TYPE


def test_amountless_component_clarifies_when_rough_estimator_unavailable(
    client: TestClient, session: Session
) -> None:
    # Boundary preserved after FTY-301: estimate-first tries rough/default estimation
    # first, but if every rough path is unavailable it may still ask rather than
    # silently commit an unsupported number.
    user_id, event_id = _seed_event(client, "fty275-amountless@example.com", "some milk")
    parsed_items: list[dict[str, Any]] = [
        {"type": "food", "name": "milk", "quantity_text": "some milk"}
    ]
    pipeline = _pipeline(
        session,
        food_source=_FakeFoodSource({}),  # USDA miss
        parsed_items=parsed_items,
        estimates=[],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION
    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
    assert _foods(session, event_id) == []
