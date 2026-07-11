"""End-to-end tests for brand-aware packaged-product routing (FTY-253).

Drive :func:`app.estimator.processing.process_estimation` with the real
:class:`ParseStep` + :class:`FoodResolveStep` + :class:`OfficialSourceResolveStep`
(parse/extraction backed by the network-free :class:`FakeProvider`, search by a
per-query scripted fake adapter, fetches by network-free fake fetchers) against
the migrated database, proving the FTY-253 acceptance criteria:

- a generic USDA FDC row naming a *different* product identity (``DENNY'S,
  chicken strips`` for ``brand=Compliments``) neither completes nor clarifies the
  branded item — the resolver searches the branded identity
  (``chicken strips Compliments``) and resolves from reference evidence, here the
  FTY-252 count-serving relation ``per 3 strips`` (the Compliments dogfood repro);
- the resolver considers more than one evidence candidate, rejecting an earlier
  incompatible one in favor of a later compatible branded/reference one;
- when the parser strands product tokens in ``quantity_text``
  (``4 toppabales brand crackers`` → ``name="crackers"``), bounded sanitized query
  variants are tried in both token orders and the successful compatible one wins;
- retailer/private-label hints are preserved into the reference query set
  (``dill pickle hummus PC Loblaws store brand nutrition facts``), built from the
  parsed fields — never a literal phrase match;
- a generic food with a good FDC match still resolves through FDC with no search,
  and barcode/OFF behavior is untouched (``tests/test_barcode_resolution.py``).
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
    SearchCandidate,
    SearchCapability,
    SearchResult,
    SearchStatus,
)
from app.estimator.searched_reference import REFERENCE_SOURCE_TYPE
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.providers.fake import FakeProvider
from app.models.derived import ClarificationQuestion, DerivedFoodItem
from app.models.food_sources import EvidenceSource

_STRIPS_URL = "https://nutrition-reference.example.com/foods/compliments-chicken-strips"
_DENNYS_URL = "https://nutrition-reference.example.com/foods/dennys-chicken-strips"
_TOPPABLES_URL = "https://nutrition-reference.example.com/foods/toppables-crackers"

# FTY-252 count-serving facts: 240 kcal per 3 strips → a logged 4 strips scales by
# 4/3 to exactly 320 kcal / 16 P / 28 C / 16 F.
_COMPLIMENTS_STRIP_FACTS = {
    "basis": "per_serving",
    "product_name": "Compliments Chicken Strips",
    "calories": 240.0,
    "protein_g": 12.0,
    "carbs_g": 21.0,
    "fat_g": 12.0,
    "serving_count": {"amount": 3.0, "unit": "strips"},
}

_FOREIGN_STRIP_FACTS = {
    **_COMPLIMENTS_STRIP_FACTS,
    "product_name": "Denny's chicken strips",
    "calories": 300.0,
}

# 90 kcal per 5 crackers (19 g) → a logged 4 crackers scales to 72 kcal / 15.2 g.
_TOPPABLES_CRACKER_FACTS = {
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

_HUMMUS_MODEL_PRIOR_FACTS = {
    "basis": "per_100g",
    "product_name": "dill pickle hummus",
    "calories": 220.0,
    "protein_g": 7.0,
    "carbs_g": 16.0,
    "fat_g": 14.0,
}


class FakeFoodSource:
    """A scripted, network-free generic-food source (USDA stand-in)."""

    def __init__(self, facts: dict[str, ProductFacts] | None = None) -> None:
        self._facts = facts or {}
        self.lookups: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    def lookup(self, query: str) -> ProductFacts | None:
        self.lookups.append(query)
        return self._facts.get(query.strip().lower())


class ScriptedSearchProvider:
    """A network-free :class:`SearchProvider` mapping each query to its result.

    Unlike a single-result fake, this scripts *per-query* outcomes so a test can
    prove one identity variant misses while another succeeds. Unknown queries
    return ``PARTIAL`` (no usable candidate).
    """

    def __init__(self, results: dict[str, SearchResult] | None = None) -> None:
        self._results = results or {}
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
        return self._results.get(query, SearchResult(status=SearchStatus.PARTIAL))


class RecordingFetcher:
    """A network-free page fetcher recording the URLs it is handed."""

    def __init__(self, text: str = "nutrition facts page text") -> None:
        self._text = text
        self.fetched: list[str] = []

    def __call__(self, url: str, settings: object) -> str:
        self.fetched.append(url)
        return self._text


def _success(*urls: str) -> SearchResult:
    return SearchResult(
        status=SearchStatus.SUCCESS,
        candidates=tuple(SearchCandidate(url=url, title="result") for url in urls),
    )


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
    food_source: FakeFoodSource,
    parsed_item: dict[str, object],
    search_provider: ScriptedSearchProvider,
    fetcher: RecordingFetcher,
    estimates: list[dict[str, Any]],
) -> Pipeline:
    """Real parse + food + official/reference pipeline with all network seams faked."""

    parse_provider = FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": [parsed_item]}]
        * SELF_CONSISTENCY_FIRST_WINDOW
    )
    official_provider = FakeProvider(responses=list(estimates))
    resolver = FoodResolver(session=session, source=food_source)
    official_step = OfficialSourceResolveStep(
        provider=official_provider,
        search_provider=search_provider,
        fetch_settings=OfficialFetchSettings(
            allowed_hosts=frozenset({"nutrition-reference.example.com"})
        ),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=fetcher,
        reference_fetch_fn=fetcher,
    )
    return Pipeline([ParseStep(parse_provider), FoodResolveStep(resolver), official_step])


def _foods(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    )


def _evidence(session: Session, event_id: uuid.UUID) -> EvidenceSource:
    return session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).one()


def _questions(session: Session, event_id: uuid.UUID) -> list[ClarificationQuestion]:
    return list(
        session.scalars(
            select(ClarificationQuestion).where(ClarificationQuestion.log_event_id == event_id)
        )
    )


def _dennys_fdc_row(*, default_serving_g: float | None) -> ProductFacts:
    return ProductFacts(
        source=FDC_SOURCE,
        source_ref="usda_fdc:777",
        query_key="chicken strips",
        description="DENNY'S, chicken strips",
        facts=NutritionFacts(calories=280.0, protein_g=15.0, carbs_g=18.0, fat_g=16.0),
        default_serving_g=default_serving_g,
        content_hash="dennyshash",
    )


def _compliments_strips_item() -> dict[str, object]:
    # The production parse shape for "compliments brand chicken strips (i had 4)":
    # brand=Compliments, name=chicken strips, amount=4 (FTY-253 acceptance).
    return {
        "type": "food",
        "name": "chicken strips",
        "brand": "Compliments",
        "quantity_text": "i had 4",
        "unit": "strips",
        "amount": 4,
    }


def test_compliments_chicken_strips_repro_resolves_from_branded_reference(
    client: TestClient, session: Session
) -> None:
    # The FTY-253 dogfood regression: a generic FDC row for the bare name — the
    # wrong brand, and with no serving grams to cost "4 strips" — must neither
    # complete the event nor raise the generic quantity question. The resolver
    # searches the branded identity and resolves from the reference page's FTY-252
    # count-serving relation, with provenance naming the evidence actually used.
    user_id, event_id = _seed_event(
        client, "fty253-repro@example.com", "compliments brand chicken strips (i had 4)"
    )
    search = ScriptedSearchProvider(
        {"chicken strips Compliments nutrition facts": _success(_STRIPS_URL)}
    )
    fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({"chicken strips": _dennys_fdc_row(default_serving_g=None)}),
        parsed_item=_compliments_strips_item(),
        search_provider=search,
        fetcher=fetcher,
        estimates=[
            {"disposition": "resolved", "confidence": 0.9, "facts": _COMPLIMENTS_STRIP_FACTS}
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []  # never the generic quantity question

    foods = _foods(session, event_id)
    assert len(foods) == 1
    food = foods[0]
    assert food.status == DerivedItemStatus.RESOLVED
    # 240 kcal per 3 strips × 4 strips consumed (FTY-252 count-serving scaling).
    assert food.calories == 320.0
    assert food.protein_g == 16.0
    assert food.carbs_g == 28.0
    assert food.fat_g == 16.0

    # Provenance reflects the evidence actually used — the reference page, never
    # the incompatible Denny's database row.
    evidence = _evidence(session, event_id)
    assert evidence.source_type == REFERENCE_SOURCE_TYPE
    assert evidence.source_ref == f"reference_source:{_STRIPS_URL}"
    assert "usda_fdc" not in (evidence.source_ref or "")

    # The branded identity was searched (official tier first, then reference).
    assert search.queries[0] == "chicken strips Compliments"
    assert "chicken strips Compliments nutrition facts" in search.queries
    assert fetcher.fetched == [_STRIPS_URL]


def test_costable_but_incompatible_fdc_row_defers_to_official_tier(
    client: TestClient, session: Session
) -> None:
    # FTY-253 replaces the former "a branded item USDA resolves never reaches the
    # official step" invariant: even when the foreign FDC row *could* cost the
    # amount (serving grams present), brand incompatibility alone rejects it — the
    # branded official-tier search runs and its page backs the item instead.
    user_id, event_id = _seed_event(
        client, "fty253-official@example.com", "compliments brand chicken strips (i had 4)"
    )
    search = ScriptedSearchProvider({"chicken strips Compliments": _success(_STRIPS_URL)})
    fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({"chicken strips": _dennys_fdc_row(default_serving_g=95.0)}),
        parsed_item=_compliments_strips_item(),
        search_provider=search,
        fetcher=fetcher,
        estimates=[
            {"disposition": "resolved", "confidence": 0.9, "facts": _COMPLIMENTS_STRIP_FACTS}
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    foods = _foods(session, event_id)
    assert len(foods) == 1
    assert foods[0].status == DerivedItemStatus.RESOLVED
    evidence = _evidence(session, event_id)
    assert evidence.source_type == OFFICIAL_SOURCE_TYPE
    assert evidence.source_ref == f"official_source:{_STRIPS_URL}"
    assert "usda_fdc:777" not in (evidence.source_ref or "")
    assert search.queries[0] == "chicken strips Compliments"
    assert fetcher.fetched == [_STRIPS_URL]


def test_costable_but_incompatible_fdc_row_is_not_persisted_as_final_match(
    client: TestClient, session: Session
) -> None:
    # Even when the foreign FDC row *could* cost the amount (serving grams present),
    # brand incompatibility alone rejects it: the branded reference result wins.
    user_id, event_id = _seed_event(
        client, "fty253-costable@example.com", "compliments brand chicken strips (i had 4)"
    )
    search = ScriptedSearchProvider(
        {"chicken strips Compliments nutrition facts": _success(_STRIPS_URL)}
    )
    fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({"chicken strips": _dennys_fdc_row(default_serving_g=95.0)}),
        parsed_item=_compliments_strips_item(),
        search_provider=search,
        fetcher=fetcher,
        estimates=[
            {"disposition": "resolved", "confidence": 0.9, "facts": _COMPLIMENTS_STRIP_FACTS}
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    evidence = _evidence(session, event_id)
    assert evidence.source_type == REFERENCE_SOURCE_TYPE
    assert evidence.source_ref == f"reference_source:{_STRIPS_URL}"


def test_incompatible_reference_candidate_rejected_in_favor_of_later_compatible_one(
    client: TestClient, session: Session
) -> None:
    # More than one evidence candidate is considered: the first result page names a
    # different brand's product and is rejected; the later compatible branded page
    # backs the item instead.
    user_id, event_id = _seed_event(
        client, "fty253-ranked@example.com", "compliments brand chicken strips (i had 4)"
    )
    search = ScriptedSearchProvider(
        {"chicken strips Compliments nutrition facts": _success(_DENNYS_URL, _STRIPS_URL)}
    )
    fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),  # plain USDA miss this time
        parsed_item=_compliments_strips_item(),
        search_provider=search,
        fetcher=fetcher,
        estimates=[
            {"disposition": "resolved", "confidence": 0.9, "facts": _FOREIGN_STRIP_FACTS},
            {"disposition": "resolved", "confidence": 0.9, "facts": _COMPLIMENTS_STRIP_FACTS},
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    food = _foods(session, event_id)[0]
    assert food.calories == 320.0  # the Compliments facts, not the Denny's 300/serving
    evidence = _evidence(session, event_id)
    assert evidence.source_ref == f"reference_source:{_STRIPS_URL}"
    # Both candidates were actually considered (fetched + extracted) in order.
    assert fetcher.fetched == [_DENNYS_URL, _STRIPS_URL]


def test_stranded_product_tokens_try_bounded_variants_until_one_succeeds(
    client: TestClient, session: Session
) -> None:
    # "4 toppabales brand crackers" can parse with the product tokens stranded in
    # quantity_text. The normalized "crackers toppabales brand ..." query misses
    # while the user-stated token order "toppabales brand crackers ..." succeeds;
    # the resolver tries the bounded variants and uses the compatible result.
    user_id, event_id = _seed_event(
        client,
        "fty253-variants@example.com",
        "4 toppabales brand crackers with 1tbsp of dill pickle hummus (PC - Loblaws store brand)",
    )
    search = ScriptedSearchProvider(
        {"toppabales brand crackers nutrition facts": _success(_TOPPABLES_URL)}
    )
    fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item={
            "type": "food",
            "name": "crackers",
            "quantity_text": "4 toppabales brand",
            "unit": "crackers",
            "amount": 4,
        },
        search_provider=search,
        fetcher=fetcher,
        estimates=[
            {"disposition": "resolved", "confidence": 0.9, "facts": _TOPPABLES_CRACKER_FACTS}
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    food = _foods(session, event_id)[0]
    # 90 kcal per 5 crackers (19 g) × 4 crackers = 72 kcal / 15.2 g.
    assert food.calories == 72.0
    assert food.grams == 15.2
    evidence = _evidence(session, event_id)
    assert evidence.source_type == REFERENCE_SOURCE_TYPE
    assert evidence.source_ref == f"reference_source:{_TOPPABLES_URL}"

    # The bounded variant set was tried in order: the base identity and the
    # normalized name+hint order missed; the user-stated token order succeeded.
    assert search.queries == [
        "crackers nutrition facts",
        "crackers toppabales brand nutrition facts",
        "toppabales brand crackers nutrition facts",
    ]
    assert fetcher.fetched == [_TOPPABLES_URL]


def test_private_label_hint_is_preserved_into_the_reference_query_set(
    client: TestClient, session: Session
) -> None:
    # The PC hummus half of the dogfood phrase: the retailer/private-label hint the
    # parser captured must reach the reference query set as a variant equivalent to
    # "dill pickle hummus PC Loblaws store brand nutrition facts" — built from the
    # parsed fields, never a literal phrase match.
    user_id, event_id = _seed_event(
        client,
        "fty253-hummus@example.com",
        "1tbsp of dill pickle hummus (PC - Loblaws store brand)",
    )
    search = ScriptedSearchProvider({})  # every variant misses → model prior
    fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item={
            "type": "food",
            "name": "dill pickle hummus",
            "brand": "PC - Loblaws store brand",
            "quantity_text": "1tbsp",
            "unit": "tbsp",
            "amount": 1,
        },
        search_provider=search,
        fetcher=fetcher,
        estimates=[
            {"disposition": "resolved", "confidence": 0.8, "facts": _HUMMUS_MODEL_PRIOR_FACTS}
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    assert "dill pickle hummus PC Loblaws store brand" in search.queries
    assert "dill pickle hummus PC Loblaws store brand nutrition facts" in search.queries


def test_generic_food_with_good_fdc_match_still_resolves_without_search(
    client: TestClient, session: Session
) -> None:
    # Existing generic resolution is preserved: an unbranded food with a good FDC
    # match resolves from the trusted database and no search query egresses.
    user_id, event_id = _seed_event(client, "fty253-generic@example.com", "150g of white rice")
    rice = ProductFacts(
        source=FDC_SOURCE,
        source_ref="usda_fdc:1",
        query_key="white rice",
        description="Rice, white, cooked",
        facts=NutritionFacts(calories=130.0, protein_g=2.0, carbs_g=28.0, fat_g=0.2),
        default_serving_g=None,
        content_hash="ricehash",
    )
    search = ScriptedSearchProvider({})
    fetcher = RecordingFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({"white rice": rice}),
        parsed_item={
            "type": "food",
            "name": "white rice",
            "quantity_text": "150g",
            "unit": "g",
            "amount": 150,
        },
        search_provider=search,
        fetcher=fetcher,
        estimates=[],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    food = _foods(session, event_id)[0]
    assert food.calories == 195.0
    evidence = _evidence(session, event_id)
    assert evidence.source_type == "trusted_nutrition_database"
    assert search.queries == []
    assert fetcher.fetched == []
