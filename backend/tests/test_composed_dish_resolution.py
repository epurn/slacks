"""FTY-368 composed-dish resolution routing tests.

Network-free pipeline coverage for the 2026-07-16 live incident: a
``tuna salad sandwich on white bread, about 1/2 a can of tuna`` must never
commit an absurd whole-dish total. Two compounding failures are pinned here:

1. the common-portion table must not apply a bare 30 g bread-slice weight as the
   whole sandwich's grams (composed-dish guard in ``common_portions.py``), and
2. a trusted per-100g row whose serving math still lands an implausible
   dish-class total must trip the resolved-value plausibility gate
   (``resolved_plausibility.py``) and refit through the rough model-prior tier
   with honest provenance — never a terminal failure and never the absurd value.
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
from app.estimator.food_resolvers import FoodResolver
from app.estimator.food_serving import NutritionFacts
from app.estimator.food_step import FoodResolveStep
from app.estimator.official_fetch import OfficialFetchSettings
from app.estimator.official_step import OfficialSourceResolveStep
from app.estimator.parse import ParseStep
from app.estimator.pipeline import Pipeline
from app.estimator.processing import process_estimation
from app.estimator.reference_fetch import ReferenceFetchSettings
from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    SearchCapability,
    SearchResult,
    SearchStatus,
)
from app.estimator.searched_reference import MODEL_PRIOR_SOURCE_TYPE
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.providers.fake import FakeProvider
from app.models.derived import ClarificationQuestion, DerivedFoodItem
from app.models.estimation import EstimationRun
from app.models.food_sources import EvidenceSource

_SANDWICH_NAME = "tuna salad sandwich on white bread"
_SANDWICH_QUANTITY = "about 1/2 a can of tuna"
_SANDWICH_RAW_TEXT = f"{_SANDWICH_NAME}, {_SANDWICH_QUANTITY}"

#: The live incident's matched row: "tuna salad", 218 kcal / 100 g, per-100g basis.
_TUNA_SALAD_PER_100G = NutritionFacts(calories=218.0, protein_g=12.0, carbs_g=9.0, fat_g=15.0)


class FakeFoodSource:
    """A scripted, network-free USDA stand-in."""

    def __init__(self, facts: dict[str, ProductFacts]) -> None:
        self._facts = facts
        self.lookups: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    def lookup(self, query: str) -> ProductFacts | None:
        self.lookups.append(query)
        return self._facts.get(query.strip().lower())


class DisabledSearchProvider:
    """Search disabled so the refit falls directly to the model-prior tier."""

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
            kinds=("named_product", "restaurant_item"),
            enabled=False,
            available=False,
        )

    def search(self, query: str) -> SearchResult:  # pragma: no cover - disabled
        return SearchResult(status=SearchStatus.PARTIAL)


def _unused_fetch(url: str, settings: object) -> str:  # pragma: no cover - search disabled
    raise AssertionError("fetch must not run when search is disabled")


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


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


def _tuna_salad_row(default_serving_g: float | None) -> ProductFacts:
    return ProductFacts(
        source=FDC_SOURCE,
        source_ref="usda_fdc:170299",
        query_key=_SANDWICH_NAME,
        description="Tuna salad",
        facts=_TUNA_SALAD_PER_100G,
        default_serving_g=default_serving_g,
        content_hash="tuna-salad-hash",
        barcode=None,
    )


def _sandwich_pipeline(
    session: Session, *, food_source: FakeFoodSource, model_estimate: dict[str, Any]
) -> Pipeline:
    parsed_items = [
        {
            "type": "food",
            "name": _SANDWICH_NAME,
            "quantity_text": _SANDWICH_QUANTITY,
            "unit": "sandwich",
            "amount": 1,
        }
    ]
    parse_provider = FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": parsed_items}]
        * SELF_CONSISTENCY_FIRST_WINDOW
    )
    official_step = OfficialSourceResolveStep(
        provider=FakeProvider(responses=[model_estimate]),
        search_provider=DisabledSearchProvider(),
        fetch_settings=OfficialFetchSettings(allowed_hosts=frozenset({"example.com"})),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=_unused_fetch,
        reference_fetch_fn=_unused_fetch,
    )
    return Pipeline(
        [
            ParseStep(parse_provider),
            FoodResolveStep(FoodResolver(session=session, source=food_source)),
            official_step,
        ]
    )


def _sandwich_model_estimate() -> dict[str, Any]:
    return {
        "disposition": "resolved",
        "confidence": 0.8,
        "facts": {
            "basis": "per_serving",
            "calories": 340.0,
            "protein_g": 22.0,
            "carbs_g": 28.0,
            "fat_g": 15.0,
            "serving_size_amount": 250.0,
            "serving_size_unit": "g",
        },
        "assumptions": ["typical deli sandwich"],
    }


def _food_items(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    )


def _evidence(session: Session, event_id: uuid.UUID) -> list[EvidenceSource]:
    return list(
        session.scalars(select(EvidenceSource).where(EvidenceSource.log_event_id == event_id))
    )


def _questions(session: Session, event_id: uuid.UUID) -> list[ClarificationQuestion]:
    return list(
        session.scalars(
            select(ClarificationQuestion).where(ClarificationQuestion.log_event_id == event_id)
        )
    )


def _run_trace(session: Session, event_id: uuid.UUID) -> str:
    run = session.scalars(select(EstimationRun).where(EstimationRun.log_event_id == event_id)).one()
    return repr(run.trace)


def test_tuna_salad_sandwich_never_costs_as_a_bare_bread_slice(
    client: TestClient, session: Session
) -> None:
    """The incident regression: no serving size → rough refit, not a 30 g slice."""

    user_id, event_id = _seed_event(client, "fty368-incident@example.com", _SANDWICH_RAW_TEXT)
    food_source = FakeFoodSource({_SANDWICH_NAME: _tuna_salad_row(default_serving_g=None)})
    pipeline = _sandwich_pipeline(
        session, food_source=food_source, model_estimate=_sandwich_model_estimate()
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    food = _food_items(session, event_id)[0]
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.calories is not None
    assert 250.0 <= food.calories <= 450.0
    evidence = _evidence(session, event_id)[0]
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert evidence.source_ref == "model_prior"
    assumptions = tuple(evidence.assumptions or [])
    # The rough refit is honest — never presented as a trusted database value —
    # and no bread-slice common portion backs the whole dish.
    assert any("model prior" in assumption for assumption in assumptions)
    assert not any(
        assumption.startswith("estimated_common_portion:bread") for assumption in assumptions
    )


def test_implausible_trusted_row_total_trips_the_gate_and_refits(
    client: TestClient, session: Session
) -> None:
    """A 65-kcal sandwich from real serving math is rejected and re-estimated."""

    user_id, event_id = _seed_event(client, "fty368-gate@example.com", _SANDWICH_RAW_TEXT)
    # With a 30 g default serving the count path lands 218 × 0.3 = 65.4 kcal —
    # exactly the incident's absurd total, now produced by clean serving math.
    food_source = FakeFoodSource({_SANDWICH_NAME: _tuna_salad_row(default_serving_g=30.0)})
    pipeline = _sandwich_pipeline(
        session, food_source=food_source, model_estimate=_sandwich_model_estimate()
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    food = _food_items(session, event_id)[0]
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.calories == pytest.approx(340.0)
    evidence = _evidence(session, event_id)[0]
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assumptions = tuple(evidence.assumptions or [])
    assert "resolved_plausibility_refit:dish_total_below_class_band" in assumptions
    # The rejection is traced content-free so the refit route stays explainable.
    assert "rejected_implausible_resolved_total" in _run_trace(session, event_id)


def test_plausible_dish_totals_commit_from_the_trusted_row_unchanged(
    client: TestClient, session: Session
) -> None:
    """The gate is a no-op for a plausible total: trusted provenance is kept."""

    user_id, event_id = _seed_event(client, "fty368-noop@example.com", _SANDWICH_RAW_TEXT)
    # A 150 g default serving lands 327 kcal — inside the dish band and above
    # the stated half-can component floor, so the trusted row stands.
    food_source = FakeFoodSource({_SANDWICH_NAME: _tuna_salad_row(default_serving_g=150.0)})
    pipeline = _sandwich_pipeline(
        session, food_source=food_source, model_estimate=_sandwich_model_estimate()
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    food = _food_items(session, event_id)[0]
    assert food.calories == pytest.approx(327.0)
    evidence = _evidence(session, event_id)[0]
    assert evidence.source_type == "trusted_nutrition_database"
    assert not any(
        assumption.startswith("resolved_plausibility_refit")
        for assumption in tuple(evidence.assumptions or [])
    )
