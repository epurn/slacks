"""FTY-301 estimate-first food-resolution fallback tests.

These drive the real parse -> food-resolution -> official/reference/model-prior
pipeline with network-free fakes. The regression class is recognized food that used
to stop at the generic quantity question after a source miss or unscalable source
match. Default ``estimate_first`` now falls forward to rough model/default serving
provenance; ``strict`` can still ask.
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
from app.estimator.food_resolvers import BarcodeResolver, FoodResolver
from app.estimator.food_serving import NutritionFacts
from app.estimator.food_step import FoodResolveStep
from app.estimator.off import OFF_SOURCE, OffMissReason, normalize_barcode
from app.estimator.official_fetch import OfficialFetchSettings
from app.estimator.official_step import (
    QUANTITY_QUESTION,
    UNKNOWN_FOOD_QUESTION,
    OfficialSourceResolveStep,
)
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
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider
from app.models.derived import ClarificationQuestion, DerivedFoodItem
from app.models.estimation import EstimationRun
from app.models.food_sources import EvidenceSource
from app.settings import DEFAULT_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR, EstimatorClarifyMode

_BARCODE = "0123456789012"
_TOPPABLES_REPRO = "3 toppables PB sandwiches (kraft)"


class FakeFoodSource:
    """A scripted, network-free USDA stand-in."""

    def __init__(
        self,
        facts: dict[str, ProductFacts] | None = None,
        *,
        enabled: bool = True,
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


class FakeBarcodeSource:
    """A scripted, network-free OFF stand-in."""

    def __init__(self, facts: dict[str, ProductFacts] | None = None) -> None:
        self._facts = facts or {}
        self.lookups: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    def lookup(self, barcode: str) -> ProductFacts | None:
        self.lookups.append(barcode)
        return self._facts.get(normalize_barcode(barcode) or "")

    def lookup_outcome(self, barcode: str) -> tuple[ProductFacts | None, OffMissReason | None]:
        facts = self.lookup(barcode)
        return facts, (None if facts is not None else OffMissReason.NO_MATCH)


class DisabledSearchProvider:
    """Search disabled so the pipeline falls directly to model-prior/default."""

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


def _pipeline(
    session: Session,
    *,
    parsed_items: list[dict[str, Any]],
    estimates: list[dict[str, Any] | LLMError],
    food_source: FakeFoodSource | None = None,
    barcode_source: FakeBarcodeSource | None = None,
    clarify_mode: EstimatorClarifyMode = "estimate_first",
    model_prior_confidence_floor: float = DEFAULT_ESTIMATOR_MODEL_PRIOR_CONFIDENCE_FLOOR,
) -> Pipeline:
    parse_provider = FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": parsed_items}]
        * SELF_CONSISTENCY_FIRST_WINDOW
    )
    resolver = FoodResolver(session=session, source=food_source or FakeFoodSource({}))
    barcode_resolver = None
    if barcode_source is not None:
        barcode_resolver = BarcodeResolver(session=session, source=barcode_source)
    official_step = OfficialSourceResolveStep(
        provider=FakeProvider(responses=estimates),
        search_provider=DisabledSearchProvider(),
        fetch_settings=OfficialFetchSettings(allowed_hosts=frozenset({"example.com"})),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=_unused_fetch,
        reference_fetch_fn=_unused_fetch,
        clarify_mode=clarify_mode,
        model_prior_confidence_floor=model_prior_confidence_floor,
    )
    return Pipeline(
        [
            ParseStep(parse_provider),
            FoodResolveStep(
                resolver,
                barcode_resolver=barcode_resolver,
                clarify_mode=clarify_mode,
            ),
            official_step,
        ]
    )


def _foods(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
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


def _run(session: Session, event_id: uuid.UUID) -> EstimationRun:
    return session.scalars(
        select(EstimationRun).where(EstimationRun.log_event_id == event_id)
    ).one()


def _source_facts_without_serving(source: str, source_ref: str, query_key: str) -> ProductFacts:
    return ProductFacts(
        source=source,
        source_ref=source_ref,
        query_key=query_key,
        description=query_key,
        facts=NutritionFacts(calories=80.0, protein_g=3.0, carbs_g=12.0, fat_g=2.0),
        default_serving_g=None,
        content_hash=f"{query_key}-hash",
        barcode=_BARCODE if source == OFF_SOURCE else None,
    )


def _per_serving_estimate(
    *,
    calories: float = 180.0,
    serving_g: float = 42.0,
    confidence: float = 0.72,
    assumptions: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "disposition": "resolved",
        "confidence": confidence,
        "facts": {
            "basis": "per_serving",
            "calories": calories,
            "protein_g": 6.0,
            "carbs_g": 22.0,
            "fat_g": 8.0,
            "serving_size_amount": serving_g,
            "serving_size_unit": "g",
        },
        "assumptions": assumptions or ["typical serving"],
    }


def _assert_model_prior_rough(evidence: EvidenceSource) -> None:
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert evidence.source_ref == "model_prior"
    assert evidence.product_id is None
    assert evidence.assumptions is not None
    assert any("model prior" in assumption for assumption in evidence.assumptions)


def test_fdc_match_with_unresolvable_serving_falls_to_model_prior_default(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "fty301-fdc@example.com", "two bowls of soup")
    food_source = FakeFoodSource(
        {"soup": _source_facts_without_serving(FDC_SOURCE, "usda_fdc:soup", "soup")}
    )
    pipeline = _pipeline(
        session,
        food_source=food_source,
        parsed_items=[
            {
                "type": "food",
                "name": "soup",
                "quantity_text": "two bowls",
                "unit": "bowls",
                "amount": 2,
            }
        ],
        estimates=[_per_serving_estimate(calories=150.0, serving_g=300.0)],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    food = _foods(session, event_id)[0]
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.calories == pytest.approx(300.0)
    assert food_source.lookups == ["soup"]
    _assert_model_prior_rough(_evidence(session, event_id)[0])


def test_off_match_with_unresolvable_serving_falls_to_model_prior_default(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "fty301-off@example.com", "two cans of cola")
    off = FakeBarcodeSource(
        {_BARCODE: _source_facts_without_serving(OFF_SOURCE, f"{OFF_SOURCE}:{_BARCODE}", _BARCODE)}
    )
    pipeline = _pipeline(
        session,
        barcode_source=off,
        parsed_items=[
            {
                "type": "food",
                "name": "cola",
                "quantity_text": "two cans",
                "unit": "cans",
                "amount": 2,
                "barcode": _BARCODE,
            }
        ],
        estimates=[_per_serving_estimate(calories=140.0, serving_g=355.0)],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    food = _foods(session, event_id)[0]
    assert food.calories == pytest.approx(280.0)
    assert off.lookups == [_BARCODE]
    evidence = _evidence(session, event_id)[0]
    _assert_model_prior_rough(evidence)
    assert "estimated_default_serving" in (evidence.assumptions or [])


@pytest.mark.parametrize(
    ("raw_text", "unit"),
    [
        (_TOPPABLES_REPRO, "cracker sandwich"),
        ("three Kraft Toppables peanut butter cracker sandwiches", "sandwiches"),
    ],
)
def test_toppables_pb_sandwich_variants_resolve_without_quantity_question(
    client: TestClient, session: Session, raw_text: str, unit: str
) -> None:
    user_id, event_id = _seed_event(
        client,
        f"fty301-toppables-{unit.replace(' ', '-')}@example.com",
        raw_text,
    )
    pipeline = _pipeline(
        session,
        parsed_items=[
            {
                "type": "food",
                "name": "Toppables peanut butter cracker sandwiches",
                "brand": "Kraft",
                "quantity_text": "3",
                "unit": unit,
                "amount": 3,
            }
        ],
        estimates=[_per_serving_estimate()],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    food = _foods(session, event_id)[0]
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.calories is not None
    assert food.calories > 0

    evidence = _evidence(session, event_id)[0]
    _assert_model_prior_rough(evidence)
    persisted_run_metadata = repr(
        (
            _run(session, event_id).trace,
            _run(session, event_id).assumptions,
            _run(session, event_id).source_refs,
            _run(session, event_id).validation_errors,
            _run(session, event_id).error,
            evidence.assumptions,
            evidence.source_ref,
        )
    )
    assert raw_text not in persisted_run_metadata
    assert QUANTITY_QUESTION not in persisted_run_metadata


@pytest.mark.parametrize(
    ("raw_text", "parsed_item"),
    [
        (
            "3 cracker sandwiches",
            {
                "type": "food",
                "name": "cracker sandwiches",
                "quantity_text": "3",
                "unit": "cracker sandwich",
                "amount": 3,
            },
        ),
        (
            "a chicken wrap",
            {
                "type": "food",
                "name": "chicken wrap",
                "quantity_text": "a wrap",
                "unit": "wrap",
                "amount": 1,
            },
        ),
        (
            "a bowl of chili",
            {
                "type": "food",
                "name": "chili",
                "quantity_text": "a bowl",
                "unit": "bowl",
                "amount": 1,
            },
        ),
    ],
)
def test_counted_composites_do_not_clarify_for_missing_source_grams(
    client: TestClient, session: Session, raw_text: str, parsed_item: dict[str, Any]
) -> None:
    user_id, event_id = _seed_event(
        client,
        f"fty301-composite-{parsed_item['name'].replace(' ', '-')}@example.com",
        raw_text,
    )
    pipeline = _pipeline(
        session,
        parsed_items=[parsed_item],
        estimates=[_per_serving_estimate(serving_g=250.0)],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    food = _foods(session, event_id)[0]
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.calories is not None
    assert food.calories > 0
    _assert_model_prior_rough(_evidence(session, event_id)[0])


@pytest.mark.parametrize(
    ("raw_text", "parsed_items", "estimates_count"),
    [
        (
            "crackers and hummus",
            [
                {"type": "food", "name": "crackers", "quantity_text": ""},
                {"type": "food", "name": "hummus", "quantity_text": ""},
            ],
            2,
        ),
        ("some milk", [{"type": "food", "name": "milk", "quantity_text": "some milk"}], 1),
        ("milk", [{"type": "food", "name": "milk", "quantity_text": ""}], 1),
    ],
)
def test_amountless_recognized_foods_are_rough_estimated_in_default_mode(
    client: TestClient,
    session: Session,
    raw_text: str,
    parsed_items: list[dict[str, Any]],
    estimates_count: int,
) -> None:
    user_id, event_id = _seed_event(
        client,
        f"fty301-amountless-{raw_text.replace(' ', '-')}@example.com",
        raw_text,
    )
    pipeline = _pipeline(
        session,
        parsed_items=parsed_items,
        estimates=[_per_serving_estimate(serving_g=30.0)] * estimates_count,
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    foods = _foods(session, event_id)
    assert len(foods) == len(parsed_items)
    assert {food.status for food in foods} == {DerivedItemStatus.RESOLVED}
    evidence_rows = _evidence(session, event_id)
    assert len(evidence_rows) == len(parsed_items)
    for evidence in evidence_rows:
        _assert_model_prior_rough(evidence)
        assert "estimated_default_serving" in (evidence.assumptions or [])


def test_model_prior_as_logged_fallback_resolves_without_grams(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "fty301-aslogged@example.com", "mystery snack")
    pipeline = _pipeline(
        session,
        parsed_items=[{"type": "food", "name": "mystery snack", "quantity_text": ""}],
        estimates=[
            {
                "disposition": "resolved",
                "confidence": 0.7,
                "facts": {
                    "basis": "as_logged",
                    "calories": 210.0,
                    "protein_g": 4.0,
                    "carbs_g": 28.0,
                    "fat_g": 8.0,
                },
                "assumptions": ["bounded as-logged estimate"],
            }
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    food = _foods(session, event_id)[0]
    assert food.grams is None
    assert food.calories == 210.0
    evidence = _evidence(session, event_id)[0]
    assert evidence.basis == "as_logged"
    assert "as_logged_model_prior" in (evidence.assumptions or [])


def test_low_confidence_model_prior_does_not_persist_completed_row(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "fty301-low-prior@example.com", "some snack")
    pipeline = _pipeline(
        session,
        parsed_items=[{"type": "food", "name": "snack", "quantity_text": "some"}],
        estimates=[_per_serving_estimate(confidence=0.59)],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION
    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
    assert _foods(session, event_id) == []
    assert _evidence(session, event_id) == []
    assert [question.question_text for question in _questions(session, event_id)] == [
        UNKNOWN_FOOD_QUESTION
    ]


def test_configured_model_prior_confidence_floor_is_enforced(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "fty301-floor@example.com", "some snack")
    pipeline = _pipeline(
        session,
        parsed_items=[{"type": "food", "name": "snack", "quantity_text": "some"}],
        estimates=[_per_serving_estimate(confidence=0.72)],
        model_prior_confidence_floor=0.73,
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION
    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
    assert _foods(session, event_id) == []
    assert _evidence(session, event_id) == []


def test_strict_mode_can_still_ask_for_unresolvable_quantity(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "fty301-strict@example.com", "two bowls of soup")
    food_source = FakeFoodSource(
        {"soup": _source_facts_without_serving(FDC_SOURCE, "usda_fdc:soup", "soup")}
    )
    pipeline = _pipeline(
        session,
        food_source=food_source,
        clarify_mode="strict",
        parsed_items=[
            {
                "type": "food",
                "name": "soup",
                "quantity_text": "two bowls",
                "unit": "bowls",
                "amount": 2,
            }
        ],
        estimates=[],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION
    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
    assert _foods(session, event_id) == []
    questions = _questions(session, event_id)
    assert [question.question_text for question in questions] == [QUANTITY_QUESTION]
