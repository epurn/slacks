"""Official/reference/model-prior count-serving resolution coverage (FTY-252)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import NamedTuple

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import DerivedItemStatus, LogEventStatus
from app.estimator.processing import process_estimation
from app.estimator.reference_fetch import ReferenceFetchSettings
from app.estimator.search import OFFICIAL_SOURCE_TYPE
from app.estimator.searched_reference import MODEL_PRIOR_SOURCE_TYPE
from app.models.estimation import EstimationRun
from app.schemas.official_source import OFFICIAL_SOURCE_SCHEMA_VERSION
from tests.test_official_source_resolution import (
    _BIG_MAC_URL,
    FakeFoodSource,
    FakeSearchProvider,
    RecordingFetcher,
    _evidence,
    _foods,
    _pipeline,
    _seed_event,
    _success_result,
)


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


_COUNT_STRIP_FACTS = {
    "basis": "per_serving",
    "product_name": "Compliments chicken strips",
    "calories": 230.0,
    "protein_g": 11.0,
    "carbs_g": 19.0,
    "fat_g": 12.0,
    "serving_count": {"amount": 3.0, "unit": "strips"},
}

_COUNT_SLICE_FACTS = {
    "basis": "per_serving",
    "product_name": "Pizza slice",
    "calories": 120.0,
    "protein_g": 6.0,
    "carbs_g": 14.0,
    "fat_g": 4.0,
    "serving_count": {"amount": 1.0, "unit": "slice"},
}

_COUNT_EGG_FACTS = {
    "basis": "per_serving",
    "product_name": "Eggs",
    "calories": 140.0,
    "protein_g": 12.0,
    "carbs_g": 1.0,
    "fat_g": 10.0,
    "serving_count": {"amount": 2.0, "unit": "eggs"},
}

_TOPPABLES_FACTS = {
    "basis": "per_serving",
    "product_name": "Toppables crackers",
    "calories": 90.0,
    "protein_g": 2.0,
    "carbs_g": 12.0,
    "fat_g": 3.0,
    "serving_size_amount": 19.0,
    "serving_size_unit": "g",
    "serving_count": {"amount": 5.0, "unit": "crackers"},
}

_MODEL_PRIOR_COUNT_FACTS = {
    "basis": "per_100g",
    "product_name": "Crackers",
    "calories": 400.0,
    "protein_g": 8.0,
    "carbs_g": 70.0,
    "fat_g": 10.0,
    "serving_size_amount": 30.0,
    "serving_size_unit": "g",
    "serving_count": {"amount": 5.0, "unit": "crackers"},
}


class CountServingCase(NamedTuple):
    email: str
    facts: dict[str, object]
    name: str
    brand: str
    unit: str
    amount: float
    quantity_text: str
    expected_calories: float
    expected_protein: float
    expected_carbs: float
    expected_fat: float


def _run(session: Session, run_id: uuid.UUID) -> EstimationRun:
    run = session.get(EstimationRun, run_id)
    assert run is not None
    return run


def _counted_item(
    *, name: str, brand: str, unit: str, amount: float, quantity_text: str
) -> dict[str, object]:
    return {
        "type": "food",
        "name": name,
        "brand": brand,
        "quantity_text": quantity_text,
        "unit": unit,
        "amount": amount,
    }


def test_official_source_schema_version_records_count_serving_shape() -> None:
    assert OFFICIAL_SOURCE_SCHEMA_VERSION == "official_source/v2"


@pytest.mark.parametrize(
    "case",
    [
        CountServingCase(
            "official-count-strips@example.com",
            _COUNT_STRIP_FACTS,
            "chicken strips",
            "Compliments",
            "strips",
            4.0,
            "4 strips",
            306.7,
            14.7,
            25.3,
            16.0,
        ),
        CountServingCase(
            "official-count-slices@example.com",
            _COUNT_SLICE_FACTS,
            "pizza",
            "Slice Shop",
            "slices",
            2.0,
            "2 slices",
            240.0,
            12.0,
            28.0,
            8.0,
        ),
        CountServingCase(
            "official-count-eggs@example.com",
            _COUNT_EGG_FACTS,
            "eggs",
            "Hen House",
            "eggs",
            3.0,
            "3 eggs",
            210.0,
            18.0,
            1.5,
            15.0,
        ),
    ],
)
def test_official_count_serving_resolves_by_consumed_count(
    client: TestClient,
    session: Session,
    case: CountServingCase,
) -> None:
    user_id, event_id = _seed_event(client, case.email, case.quantity_text)
    search = FakeSearchProvider(_success_result())
    fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item=_counted_item(
            name=case.name,
            brand=case.brand,
            unit=case.unit,
            amount=case.amount,
            quantity_text=case.quantity_text,
        ),
        search_provider=search,
        fetcher=fetcher,
        estimates=[{"disposition": "resolved", "confidence": 0.9, "facts": case.facts}],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    assert result.run_id is not None
    food = _foods(session, event_id)[0]
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.grams is None
    assert food.calories == pytest.approx(case.expected_calories)
    assert food.protein_g == pytest.approx(case.expected_protein)
    assert food.carbs_g == pytest.approx(case.expected_carbs)
    assert food.fat_g == pytest.approx(case.expected_fat)

    evidence = _evidence(session, event_id)
    assert evidence.source_type == OFFICIAL_SOURCE_TYPE
    assert evidence.source_ref == f"official_source:{_BIG_MAC_URL}"
    assert evidence.basis == "per_serving"
    assert evidence.assumptions is None
    assert _run(session, result.run_id).schema_version == OFFICIAL_SOURCE_SCHEMA_VERSION


def test_official_count_serving_with_grams_uses_count_not_full_servings(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(
        client, "official-toppables@example.com", "4 Toppables crackers"
    )
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item=_counted_item(
            name="Toppables crackers",
            brand="Dare",
            unit="crackers",
            amount=4.0,
            quantity_text="4 crackers",
        ),
        search_provider=FakeSearchProvider(_success_result()),
        fetcher=RecordingFetcher(),
        estimates=[{"disposition": "resolved", "confidence": 0.9, "facts": _TOPPABLES_FACTS}],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    food = _foods(session, event_id)[0]
    assert food.grams == pytest.approx(15.2)
    assert food.calories == pytest.approx(72.0)
    assert food.protein_g == pytest.approx(1.6)
    assert food.carbs_g == pytest.approx(9.6)
    assert food.fat_g == pytest.approx(2.4)
    assert food.grams != pytest.approx(76.0)  # 4 whole 19 g servings would be wrong.

    evidence = _evidence(session, event_id)
    assert evidence.source_type == OFFICIAL_SOURCE_TYPE
    assert evidence.basis == "per_serving"
    assert evidence.calories_per_100g == 90.0
    assert evidence.assumptions is None


def test_model_prior_count_serving_per_100g_uses_count_relation_for_grams(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "model-count-crackers@example.com", "4 crackers")
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item={
            "type": "food",
            "name": "crackers",
            "quantity_text": "4 crackers",
            "unit": "crackers",
            "amount": 4.0,
        },
        search_provider=FakeSearchProvider(_success_result(), enabled=False),
        fetcher=RecordingFetcher(),
        estimates=[
            {
                "disposition": "resolved",
                "confidence": 0.7,
                "facts": _MODEL_PRIOR_COUNT_FACTS,
                "assumptions": ["typical cracker serving"],
            }
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    food = _foods(session, event_id)[0]
    assert food.grams == pytest.approx(24.0)
    assert food.calories == pytest.approx(96.0)
    assert food.grams != pytest.approx(120.0)
    assert food.calories != pytest.approx(480.0)

    evidence = _evidence(session, event_id)
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert evidence.basis == "per_100g"
    assert evidence.assumptions is not None
    assert "model_prior_count_serving:5 cracker" in evidence.assumptions


def test_incompatible_count_serving_falls_through_instead_of_scaling(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(
        client, "official-count-incompatible@example.com", "2 cups chicken strips"
    )
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item=_counted_item(
            name="chicken strips",
            brand="Compliments",
            unit="cups",
            amount=2.0,
            quantity_text="2 cups",
        ),
        search_provider=FakeSearchProvider(_success_result()),
        fetcher=RecordingFetcher(),
        reference_settings=ReferenceFetchSettings(enabled=False),
        estimates=[
            {"disposition": "resolved", "confidence": 0.9, "facts": _COUNT_STRIP_FACTS},
            {
                "disposition": "resolved",
                "confidence": 0.7,
                "facts": {
                    "basis": "as_logged",
                    "calories": 300.0,
                    "protein_g": 20.0,
                    "carbs_g": 15.0,
                    "fat_g": 12.0,
                },
                "assumptions": ["as logged model prior"],
            },
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    food = _foods(session, event_id)[0]
    assert food.calories == 300.0
    assert food.calories != pytest.approx(153.3)  # 2/3 of the strip serving.
    evidence = _evidence(session, event_id)
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert evidence.basis == "as_logged"
