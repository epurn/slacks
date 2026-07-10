"""FTY-254 common-food dogfood fixture set (integration-style).

Drives the real parse → food-resolution → official/reference/model-prior
pipeline through the production worker entrypoint, with a **real**
:class:`FdcClient` fed fake FDC result lists over a network-free transport — so
the FTY-254 ranking (form rejection, head-noun gate, preference order) and the
common-portion serving fallback are exercised end-to-end, down to the persisted
rows. Each case asserts a rough calorie band plus source/provenance shape.

Fixture nutrient values are public USDA FDC per-100g figures (SR Legacy); the
log phrases are synthetic. The search provider is disabled, so a deferred
candidate falls straight to the scripted model prior — the rough tiers' own
search/fetch behavior is covered by ``test_official_source_resolution.py``.
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
from app.estimator.fdc import FDC_SOURCE, FDC_SOURCE_TYPE, FdcClient, FdcSettings
from app.estimator.food_step import FoodResolver, FoodResolveStep
from app.estimator.official_fetch import OfficialFetchSettings
from app.estimator.official_step import QUANTITY_QUESTION, OfficialSourceResolveStep
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
from app.estimator.searched_reference import MODEL_PRIOR_SOURCE, MODEL_PRIOR_SOURCE_TYPE
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider
from app.models.derived import ClarificationQuestion, DerivedFoodItem
from app.models.food_sources import EvidenceSource, Product

# ---------------------------------------------------------------------------
# Fake FDC search results (public USDA SR Legacy per-100g values)
# ---------------------------------------------------------------------------


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


_RAW_BANANA = _fdc_food(9040, "Bananas, raw", 89.0, 1.09, 22.84, 0.33)
_DEHYDRATED_BANANA = _fdc_food(
    9041, "Bananas, dehydrated, or banana powder", 346.0, 3.89, 88.28, 1.81
)
_RAW_EGG = _fdc_food(1123, "Egg, whole, raw, fresh", 143.0, 12.56, 0.72, 9.51)
_SCRAMBLED_EGG = _fdc_food(1132, "Egg, whole, cooked, scrambled", 149.0, 9.99, 1.61, 10.98)
_WHEAT_TOAST = _fdc_food(
    20090, "Bread, whole-wheat, commercially prepared, toasted", 306.0, 12.45, 51.16, 4.27
)
_WHITE_TOAST = _fdc_food(
    20091, "Bread, white, commercially prepared, toasted", 293.0, 8.85, 54.4, 3.6
)
_PICKLES = _fdc_food(
    11937, "Pickles, cucumber, dill or kosher dill", 11.0, 0.33, 2.41, 0.2, serving_g=65.0
)
_BREWED_COFFEE = _fdc_food(
    14209, "Beverages, coffee, brewed, prepared with tap water", 1.0, 0.12, 0.0, 0.02
)

#: What the fake FDC returns per normalized query. The banana list puts the
#: dehydrated/powder row FIRST — the observed real-world relevance order the
#: FTY-254 ranking must overcome. Queries absent here return no results.
_FDC_RESPONSES: dict[str, dict[str, Any]] = {
    "banana": {"foods": [_DEHYDRATED_BANANA, _RAW_BANANA]},
    "eggs": {"foods": [_RAW_EGG]},
    "scrambled eggs": {"foods": [_RAW_EGG, _SCRAMBLED_EGG]},
    "wheat toast": {"foods": [_WHEAT_TOAST]},
    "buttered toast": {"foods": [_WHITE_TOAST]},
    "dill pickle hummus": {"foods": [_PICKLES]},
    "dill pickles": {"foods": [_PICKLES]},
    "coffee": {"foods": [_BREWED_COFFEE]},
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


def _pipeline(
    session: Session,
    *,
    parse_responses: list[dict[str, Any] | LLMError],
    estimates: list[dict[str, Any] | LLMError],
    transport: QueryKeyedTransport,
) -> Pipeline:
    parse_provider = FakeProvider(responses=parse_responses * SELF_CONSISTENCY_FIRST_WINDOW)
    fdc_client = FdcClient(FdcSettings(api_key=SecretStr("test-key")), transport=transport)
    resolver = FoodResolver(session=session, source=fdc_client)
    official_step = OfficialSourceResolveStep(
        provider=FakeProvider(responses=estimates),
        search_provider=DisabledSearchProvider(),
        fetch_settings=OfficialFetchSettings(allowed_hosts=frozenset({"example.com"})),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=_unused_fetch,
        reference_fetch_fn=_unused_fetch,
    )
    return Pipeline([ParseStep(parse_provider), FoodResolveStep(resolver), official_step])


def _parsed(items: list[dict[str, Any]]) -> list[dict[str, Any] | LLMError]:
    return [{"disposition": "parsed", "confidence": 0.92, "items": items}]


def _foods(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    )


def _evidence_for(session: Session, food: DerivedFoodItem) -> EvidenceSource:
    return session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == food.id)
    ).one()


def _questions(session: Session, event_id: uuid.UUID) -> list[ClarificationQuestion]:
    return list(
        session.scalars(
            select(ClarificationQuestion).where(ClarificationQuestion.log_event_id == event_id)
        )
    )


def _as_logged_estimate(calories: float, assumptions: list[str]) -> dict[str, Any]:
    return {
        "disposition": "resolved",
        "confidence": 0.8,
        "facts": {
            "basis": "as_logged",
            "calories": calories,
            "protein_g": 3.0,
            "carbs_g": 12.0,
            "fat_g": 6.0,
        },
        "assumptions": assumptions,
    }


# ---------------------------------------------------------------------------
# The compact v1 common-food fixture set: FDC-backed cases with calorie bands
# ---------------------------------------------------------------------------

_FDC_CASES: list[dict[str, Any]] = [
    {
        "id": "hundred-grams-banana",
        "raw_text": "100 grams banana",
        "item": {
            "type": "food",
            "name": "banana",
            "quantity_text": "100 grams",
            "unit": "g",
            "amount": 100,
        },
        # Fresh banana ≈ 89 kcal / 100 g. The dehydrated/powder row (346 kcal)
        # is listed first by the fake source and must not win.
        "calorie_band": (70.0, 110.0),
        "source_ref": "usda_fdc:9040",
        "assumption": None,
    },
    {
        "id": "one-banana",
        "raw_text": "one banana",
        "item": {
            "type": "food",
            "name": "banana",
            "quantity_text": "one",
            "unit": None,
            "amount": 1,
        },
        # One medium banana (118 g documented default) ≈ 105 kcal.
        "calorie_band": (85.0, 125.0),
        "source_ref": "usda_fdc:9040",
        "assumption": "estimated_common_portion:banana medium 118 g",
    },
    {
        "id": "two-large-eggs",
        "raw_text": "2 large eggs",
        "item": {
            "type": "food",
            "name": "eggs",
            "quantity_text": "2 large",
            "unit": "eggs",
            "amount": 2,
        },
        # Two large eggs (2 × 50 g) at 143 kcal/100g ≈ 143 kcal.
        "calorie_band": (120.0, 200.0),
        "source_ref": "usda_fdc:1123",
        "assumption": "estimated_common_portion:egg large 50 g",
    },
    {
        "id": "one-slice-wheat-toast",
        "raw_text": "1 slice wheat toast",
        "item": {
            "type": "food",
            "name": "wheat toast",
            "quantity_text": "1 slice",
            "unit": "slice",
            "amount": 1,
        },
        # One toast slice (25 g documented default) at 306 kcal/100g ≈ 77 kcal.
        "calorie_band": (55.0, 110.0),
        "source_ref": "usda_fdc:20090",
        "assumption": "estimated_common_portion:toast slice 25 g",
    },
    {
        "id": "two-dill-pickles",
        "raw_text": "2 dill pickles",
        "item": {
            "type": "food",
            "name": "dill pickles",
            "quantity_text": "2",
            "unit": None,
            "amount": 2,
        },
        # Plain "dill pickle" IS a pickle food: the pickles row stays a trusted
        # match (2 × 65 g source serving at 11 kcal/100g ≈ 14 kcal).
        "calorie_band": (5.0, 40.0),
        "source_ref": "usda_fdc:11937",
        "assumption": None,
    },
]


@pytest.mark.parametrize("case", _FDC_CASES, ids=lambda case: str(case["id"]))
def test_common_food_resolves_from_fdc_with_plausible_calories(
    client: TestClient, session: Session, case: dict[str, Any]
) -> None:
    user_id, event_id = _seed_event(client, f"fty254-{case['id']}@example.com", case["raw_text"])
    transport = QueryKeyedTransport()
    pipeline = _pipeline(
        session, parse_responses=_parsed([case["item"]]), estimates=[], transport=transport
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []

    food = _foods(session, event_id)[0]
    assert food.status == DerivedItemStatus.RESOLVED
    low, high = case["calorie_band"]
    assert food.calories is not None and low <= food.calories <= high

    evidence = _evidence_for(session, food)
    assert evidence.source_type == FDC_SOURCE_TYPE
    assert evidence.source_ref == case["source_ref"]
    assert evidence.product_id is not None  # cached global source facts
    if case["assumption"] is None:
        assert evidence.assumptions is None  # fully deterministic resolution
    else:
        # The rough portion default is explicit and labelled, never silent.
        assert evidence.assumptions == [case["assumption"]]


def test_hundred_gram_banana_is_not_costed_as_dehydrated_banana(
    client: TestClient, session: Session
) -> None:
    """The headline FTY-254 regression: 100 g of banana must not be 346 kcal."""

    user_id, event_id = _seed_event(client, "fty254-banana-form@example.com", "100 grams banana")
    pipeline = _pipeline(
        session,
        parse_responses=_parsed(
            [
                {
                    "type": "food",
                    "name": "banana",
                    "quantity_text": "100 grams",
                    "unit": "g",
                    "amount": 100,
                }
            ]
        ),
        estimates=[],
        transport=QueryKeyedTransport(),
    )

    process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    food = _foods(session, event_id)[0]
    assert food.calories == pytest.approx(89.0)
    assert food.calories != pytest.approx(346.0)
    assert _evidence_for(session, food).source_ref != "usda_fdc:9041"


# ---------------------------------------------------------------------------
# Multi-item: each recognizable component resolves independently
# ---------------------------------------------------------------------------


def test_scrambled_eggs_and_buttered_toast_resolve_without_clarification(
    client: TestClient, session: Session
) -> None:
    """Two scrambled eggs cost from the scrambled FDC row via the egg portion
    default; buttered toast rejects the plain-toast row (unstated butter) and
    lands on an explicitly labelled rough model-prior composite. The event
    completes with both components costed — one un-costable-by-FDC phrase never
    drags the entry to clarification."""

    user_id, event_id = _seed_event(
        client,
        "fty254-multi-item@example.com",
        "two scrambled eggs and one slice buttered toast",
    )
    transport = QueryKeyedTransport()
    pipeline = _pipeline(
        session,
        parse_responses=_parsed(
            [
                {
                    "type": "food",
                    "name": "scrambled eggs",
                    "quantity_text": "two",
                    "unit": "eggs",
                    "amount": 2,
                },
                {
                    "type": "food",
                    "name": "buttered toast",
                    "quantity_text": "one slice",
                    "unit": "slice",
                    "amount": 1,
                },
            ]
        ),
        estimates=[_as_logged_estimate(116.0, ["one toast slice with one pat of butter assumed"])],
        transport=transport,
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []

    foods = {food.name: food for food in _foods(session, event_id)}
    assert set(foods) == {"scrambled eggs", "buttered toast"}
    assert {food.status for food in foods.values()} == {DerivedItemStatus.RESOLVED}

    eggs = foods["scrambled eggs"]
    # The scrambled row (149 kcal/100g) is preferred over the raw-egg row for a
    # "scrambled eggs" query; 2 × 50 g large-egg default ≈ 149 kcal.
    assert eggs.calories is not None and 120.0 <= eggs.calories <= 220.0
    eggs_evidence = _evidence_for(session, eggs)
    assert eggs_evidence.source_type == FDC_SOURCE_TYPE
    assert eggs_evidence.source_ref == "usda_fdc:1132"
    assert "estimated_common_portion:egg large 50 g" in (eggs_evidence.assumptions or [])

    toast = foods["buttered toast"]
    assert toast.calories == pytest.approx(116.0)
    toast_evidence = _evidence_for(session, toast)
    assert toast_evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert toast_evidence.source_ref == MODEL_PRIOR_SOURCE
    assumptions = toast_evidence.assumptions or []
    assert any("estimated from model prior" in assumption for assumption in assumptions)
    assert "one toast slice with one pat of butter assumed" in assumptions
    # The plain-toast FDC row was consulted and rejected, not skipped.
    assert "buttered toast" in transport.queries


# ---------------------------------------------------------------------------
# Dill pickle hummus: flavor/detail vs. food identity
# ---------------------------------------------------------------------------


def _hummus_item(brand: str | None) -> dict[str, Any]:
    item: dict[str, Any] = {
        "type": "food",
        "name": "dill pickle hummus",
        "quantity_text": "1 tbsp",
        "unit": "tbsp",
        "amount": 1,
    }
    if brand is not None:
        item["brand"] = brand
    return item


@pytest.mark.parametrize(
    ("case_id", "brand"),
    [("generic", None), ("pc-store-brand", "PC")],
    ids=["1-tbsp-dill-pickle-hummus", "pc-loblaws-store-brand"],
)
def test_dill_pickle_hummus_never_resolves_through_the_pickles_row(
    client: TestClient, session: Session, case_id: str, brand: str | None
) -> None:
    """The FDC hit whose description is pickles/cucumbers is rejected for a
    hummus identity; the resolver falls through to the rough tiers instead of
    recording a ~2 kcal hummus estimate from pickles."""

    user_id, event_id = _seed_event(
        client, f"fty254-hummus-{case_id}@example.com", "1 tbsp dill pickle hummus"
    )
    transport = QueryKeyedTransport()
    pipeline = _pipeline(
        session,
        parse_responses=_parsed([_hummus_item(brand)]),
        estimates=[_as_logged_estimate(25.0, ["one tablespoon of hummus"])],
        transport=transport,
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []

    food = _foods(session, event_id)[0]
    assert food.status == DerivedItemStatus.RESOLVED
    # A tbsp of hummus is ~25 kcal — not the ~2 kcal a 15 g pickles scaling gives.
    assert food.calories == pytest.approx(25.0)

    evidence = _evidence_for(session, food)
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert evidence.source_ref == MODEL_PRIOR_SOURCE
    assert evidence.source_ref != "usda_fdc:11937"
    # FDC was consulted and its pickles row rejected — not skipped.
    assert "dill pickle hummus" in transport.queries


# ---------------------------------------------------------------------------
# Upgrade path: stale pre-FTY-254 cache rows must not bypass the ranking gate
# ---------------------------------------------------------------------------


def _seed_stale_cache_row(
    session: Session, *, query_key: str, description: str, source_ref: str, calories: float
) -> None:
    """A global FDC cache row as a pre-FTY-254 resolver would have selected it."""

    session.add(
        Product(
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
    )
    session.flush()


def test_stale_dehydrated_banana_cache_row_is_replaced_on_upgrade(
    client: TestClient, session: Session
) -> None:
    """An upgraded database that already cached ``banana -> usda_fdc:9041``
    (dehydrated/powder) must not keep costing 100 g of banana at 346 kcal: the
    stale row fails the compatibility gate on read, the ranked lookup runs, and
    the fresh raw-banana row backs the resolution and refreshes the cache row
    in place."""

    user_id, event_id = _seed_event(client, "fty254-stale-banana@example.com", "100 grams banana")
    _seed_stale_cache_row(
        session,
        query_key="banana",
        description="Bananas, dehydrated, or banana powder",
        source_ref="usda_fdc:9041",
        calories=346.0,
    )
    transport = QueryKeyedTransport()
    pipeline = _pipeline(
        session,
        parse_responses=_parsed(
            [
                {
                    "type": "food",
                    "name": "banana",
                    "quantity_text": "100 grams",
                    "unit": "g",
                    "amount": 100,
                }
            ]
        ),
        estimates=[],
        transport=transport,
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    food = _foods(session, event_id)[0]
    assert food.calories == pytest.approx(89.0)
    evidence = _evidence_for(session, food)
    assert evidence.source_type == FDC_SOURCE_TYPE
    assert evidence.source_ref == "usda_fdc:9040"
    # The stale cache row was not trusted (FDC was consulted) and was refreshed
    # in place: still exactly one global row for the key, now the compatible one.
    assert "banana" in transport.queries
    rows = session.scalars(
        select(Product).where(Product.source == FDC_SOURCE, Product.query_key == "banana")
    ).all()
    assert [row.source_ref for row in rows] == ["usda_fdc:9040"]


def test_stale_pickles_cache_row_for_hummus_falls_to_the_rough_tiers_on_upgrade(
    client: TestClient, session: Session
) -> None:
    """``dill pickle hummus -> usda_fdc:11937`` cached pre-FTY-254 is rejected on
    read; the fresh lookup returns the same pickles-only list (a clean miss), so
    the model prior records the estimate — trusted pickle provenance is never
    re-recorded from the stale cache."""

    user_id, event_id = _seed_event(
        client, "fty254-stale-hummus@example.com", "1 tbsp dill pickle hummus"
    )
    _seed_stale_cache_row(
        session,
        query_key="dill pickle hummus",
        description="Pickles, cucumber, dill or kosher dill",
        source_ref="usda_fdc:11937",
        calories=11.0,
    )
    transport = QueryKeyedTransport()
    pipeline = _pipeline(
        session,
        parse_responses=_parsed([_hummus_item(None)]),
        estimates=[_as_logged_estimate(25.0, ["one tablespoon of hummus"])],
        transport=transport,
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    food = _foods(session, event_id)[0]
    assert food.calories == pytest.approx(25.0)
    evidence = _evidence_for(session, food)
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert evidence.source_ref != "usda_fdc:11937"
    assert "dill pickle hummus" in transport.queries


# ---------------------------------------------------------------------------
# Genuinely ambiguous inputs: documented rough default or item-specific question
# ---------------------------------------------------------------------------


def test_bare_coffee_uses_a_documented_rough_default_not_a_quantity_question(
    client: TestClient, session: Session
) -> None:
    """The FTY-254 coffee policy: a bare ``coffee`` log resolves as an explicit
    rough model-prior default (black brewed coffee, one cup) under the default
    estimate-first mode — never the generic no-option quantity question."""

    user_id, event_id = _seed_event(client, "fty254-coffee@example.com", "coffee")
    pipeline = _pipeline(
        session,
        parse_responses=_parsed([{"type": "food", "name": "coffee", "quantity_text": ""}]),
        estimates=[_as_logged_estimate(2.0, ["assumed black brewed coffee, one 240 ml cup"])],
        transport=QueryKeyedTransport(),
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []

    food = _foods(session, event_id)[0]
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.calories is not None and 0.0 <= food.calories <= 10.0

    evidence = _evidence_for(session, food)
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assumptions = evidence.assumptions or []
    assert "assumed black brewed coffee, one 240 ml cup" in assumptions
    assert any("estimated from model prior" in assumption for assumption in assumptions)


def test_bare_curry_asks_an_item_specific_question_with_options(
    client: TestClient, session: Session
) -> None:
    """A genuinely ambiguous item clarifies with a specific, optioned question —
    never the generic no-option ``How much did you have...`` fallback."""

    user_id, event_id = _seed_event(client, "fty254-curry@example.com", "curry")
    curry_question = {
        "text": "What kind of curry was it?",
        "options": ["Chicken curry", "Vegetable curry", "Beef curry", "Lentil curry"],
    }
    pipeline = _pipeline(
        session,
        parse_responses=[
            {
                "disposition": "needs_clarification",
                "confidence": 0.35,
                "clarification_questions": [curry_question],
            }
        ],
        estimates=[],
        transport=QueryKeyedTransport(),
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION
    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION
    assert _foods(session, event_id) == []

    questions = _questions(session, event_id)
    assert [question.question_text for question in questions] == ["What kind of curry was it?"]
    assert questions[0].options == curry_question["options"]
    assert QUANTITY_QUESTION not in {question.question_text for question in questions}
