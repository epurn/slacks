"""FTY-418: a loosely-described sandwich resolves to real nutrition + macros.

Diagnosis regression for the 2026-07-20 dogfood (entry ``25c3047b``): a plainly
described "2 slices of deli turkey, 1 slice of mozzarella, and 15g of mustard"
must resolve each component to **real per-food calories and non-null macros with
a food-aware portion** — never a wrong-variant source match (mustard costed as
*mustard oil*) and never the deterministic coarse degrade prior (a flat
``2 cal/g + null macros + 100 g`` slice).

Drives the real parse → food-resolution → official/reference/model-prior pipeline
through the production worker entrypoint with a **real** :class:`FdcClient` fed
fake FDC result lists over a network-free transport (mirroring
``test_common_food_resolution.py``), so the FTY-418 form rejection (``oil``) and
the deli-meat / sliced-cheese common-portion defaults are exercised end-to-end
down to the persisted rows. FDC nutrient values are public USDA per-100g figures;
the log phrase is synthetic. The search provider is disabled.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import DerivedItemStatus, EstimationJobStatus, LogEventStatus
from app.estimator.fdc import FDC_SOURCE_TYPE, FdcClient, FdcSettings
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
    SearchCapability,
    SearchResult,
    SearchStatus,
)
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider
from app.models.derived import ClarificationQuestion, DerivedFoodItem
from app.models.food_sources import EvidenceSource


def _fdc_food(
    fdc_id: int,
    description: str,
    calories: float,
    protein: float,
    carbs: float,
    fat: float,
    *,
    serving_g: float | None = None,
) -> dict[str, Any]:
    food: dict[str, Any] = {
        "fdcId": fdc_id,
        "description": description,
        "foodNutrients": [
            {"nutrientId": 1008, "value": calories},
            {"nutrientId": 1003, "value": protein},
            {"nutrientId": 1005, "value": carbs},
            {"nutrientId": 1004, "value": fat},
        ],
    }
    if serving_g is not None:
        food["servingSize"] = serving_g
        food["servingSizeUnit"] = "g"
    return food


# Public USDA per-100g values. The "mustard" list puts "Oil, mustard" (884 kcal,
# pure fat) FIRST — the observed real-world relevance order that made a bare
# "mustard" cost 15 g at 132.6 kcal until FTY-418 rejected the extracted-oil form.
# The deli-turkey and mozzarella rows carry NO serving size, so the counted-slice
# portion comes from the common-portion table (food-aware, not a flat 100 g).
_OIL_MUSTARD = _fdc_food(172337, "Oil, mustard", 884.0, 0.0, 0.0, 100.0)
_PREPARED_MUSTARD = _fdc_food(172234, "Mustard, prepared, yellow", 60.0, 3.7, 5.3, 3.4)
_DELI_TURKEY = _fdc_food(171506, "Turkey, breast, sliced, prepackaged deli", 104.0, 17.1, 3.5, 2.0)
_MOZZARELLA = _fdc_food(170845, "Cheese, mozzarella, whole milk", 300.0, 22.2, 2.2, 22.4)

_FDC_RESPONSES: dict[str, dict[str, Any]] = {
    "mustard": {"foods": [_OIL_MUSTARD, _PREPARED_MUSTARD]},
    "deli turkey": {"foods": [_DELI_TURKEY]},
    "mozzarella": {"foods": [_MOZZARELLA]},
}


class QueryKeyedTransport:
    """Network-free FDC transport returning the scripted result list per query."""

    def __init__(self) -> None:
        self.queries: list[str] = []

    def __call__(self, url: str, **kwargs: Any) -> dict[str, Any]:
        query = str(kwargs["payload"]["query"])
        self.queries.append(query)
        return _FDC_RESPONSES.get(query, {"foods": []})


class DisabledSearchProvider:
    """Search disabled so a deferred candidate falls straight to model prior."""

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


def _pipeline(session: Session, parse_items: list[dict[str, Any]]) -> Pipeline:
    parse_responses: list[dict[str, Any] | LLMError] = [
        {"disposition": "parsed", "confidence": 0.92, "items": parse_items}
    ]
    parse_provider = FakeProvider(responses=parse_responses * SELF_CONSISTENCY_FIRST_WINDOW)
    fdc_client = FdcClient(
        FdcSettings(api_key=SecretStr("test-key")), transport=QueryKeyedTransport()
    )
    resolver = FoodResolver(session=session, source=fdc_client)
    official_step = OfficialSourceResolveStep(
        provider=FakeProvider(responses=[]),
        search_provider=DisabledSearchProvider(),
        fetch_settings=OfficialFetchSettings(allowed_hosts=frozenset({"example.com"})),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=_unused_fetch,
        reference_fetch_fn=_unused_fetch,
    )
    return Pipeline([ParseStep(parse_provider), FoodResolveStep(resolver), official_step])


def _foods(session: Session, event_id: uuid.UUID) -> dict[str, DerivedFoodItem]:
    rows = session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    return {food.name: food for food in rows}


def _evidence_for(session: Session, food: DerivedFoodItem) -> EvidenceSource:
    return session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == food.id)
    ).one()


def _item(name: str, quantity_text: str, unit: str, amount: float) -> dict[str, Any]:
    return {
        "type": "food",
        "name": name,
        "quantity_text": quantity_text,
        "unit": unit,
        "amount": amount,
    }


_SANDWICH_ITEMS: list[dict[str, Any]] = [
    _item("deli turkey", "2 slices", "slices", 2),
    _item("mozzarella", "1 slice", "slice", 1),
    _item("mustard", "15g", "g", 15),
]


def test_loosely_described_sandwich_resolves_to_real_nutrition_and_macros(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(
        client,
        "fty418-sandwich@example.com",
        "2 slices of deli turkey, 1 slice of mozzarella, and 15g of mustard",
    )
    pipeline = _pipeline(session, _SANDWICH_ITEMS)

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    # Every item resolves — the meal never falls to the coarse degrade prior.
    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert (
        session.scalars(
            select(ClarificationQuestion).where(ClarificationQuestion.log_event_id == event_id)
        ).all()
        == []
    )

    foods = _foods(session, event_id)
    assert set(foods) == {"deli turkey", "mozzarella", "mustard"}
    assert {f.status for f in foods.values()} == {DerivedItemStatus.RESOLVED}

    # Every item has real per-food calories AND non-null macros.
    for food in foods.values():
        assert food.calories is not None and food.calories > 0
        assert food.protein_g is not None
        assert food.carbs_g is not None
        assert food.fat_g is not None

    # AC3 — sensible match: "mustard" resolves to prepared mustard, NOT mustard oil.
    mustard = foods["mustard"]
    mustard_ev = _evidence_for(session, mustard)
    assert mustard_ev.source_ref == "usda_fdc:172234"  # prepared, not usda_fdc:172337 (oil)
    assert mustard_ev.source_ref != "usda_fdc:172337"
    # 15 g of prepared mustard (~60 kcal/100g) ≈ 9 kcal — never ~132 kcal of oil.
    assert mustard.calories is not None
    assert 5.0 <= mustard.calories <= 20.0
    assert mustard.grams == pytest.approx(15.0)

    # AC1 — food-aware portions: a deli-turkey slice ≈ 28 g (not a flat 100 g),
    # a mozzarella slice ≈ 22 g. Both come from the common-portion table.
    turkey = foods["deli turkey"]
    assert turkey.grams == pytest.approx(56.0)  # 2 × 28 g
    turkey_assumptions = _evidence_for(session, turkey).assumptions or []
    assert "estimated_common_portion:turkey slice 28 g" in turkey_assumptions

    mozzarella = foods["mozzarella"]
    assert mozzarella.grams == pytest.approx(22.0)  # 1 × 22 g, not a flat 100 g
    assert "estimated_common_portion:mozzarella slice 22 g" in (
        _evidence_for(session, mozzarella).assumptions or []
    )
    # Real trusted-database provenance, never the coarse model-prior degrade.
    assert {_evidence_for(session, f).source_type for f in foods.values()} == {FDC_SOURCE_TYPE}
