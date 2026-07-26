"""FTY-437 regression: a counted piece is not a counted serving.

The ``branded-crackers-and-hummus`` smoke failed on every run with
``item 'crackers' calories 360 outside the per-item plausible band [30, 250]``: the
cracker resolved to a *correct* Open Food Facts row (473.68 kcal / 100 g, 19 g
serving) whose serving mass was then multiplied by the piece count — ``4 x 19 g =
76 g`` at ``4.7368 kcal/g`` = 360 kcal, four whole servings instead of four crackers.

These tests drive the real parse -> food-resolution -> official/reference pipeline
with network-free fakes through **both** places that conflation lived:

- ``food_step._build_item`` — the product path (a trusted database / barcode row);
- ``resolved_item._build_item`` — the shared tier builder the OFF name tier uses,
  which is the path the reported item actually took, plus its independent
  ``_default_serving_grams`` fallback.

Each asserts the honest mass, the retained trusted per-100g facts and source ref,
and the content-free per-piece assumption label — and that serving-equivalent counts
of the same product are untouched.
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
from app.estimator.evidence_utils import _content_hash
from app.estimator.fdc import FDC_SOURCE, FDC_SOURCE_TYPE, ProductFacts, normalize_query
from app.estimator.food_resolvers import FoodResolver, OffNameResolver
from app.estimator.food_serving import NutritionFacts
from app.estimator.food_step import FoodResolveStep
from app.estimator.off import OFF_SOURCE, OFF_SOURCE_TYPE
from app.estimator.official_fetch import OfficialFetchSettings
from app.estimator.official_step import OfficialSourceResolveStep
from app.estimator.parse import ParseStep
from app.estimator.parse_policy import ParsePolicySettings
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
from app.llm.providers.fake import FakeProvider
from app.models.derived import ClarificationQuestion, DerivedFoodItem
from app.models.food_sources import EvidenceSource
from app.settings import EstimatorClarifyMode

#: The reported row's facts: correct per-100g energy, correct 19 g serving size, and
#: no stated count relation (every cached OFF row today — reading that relation is
#: FTY-439). A serving is roughly four to five crackers of ~3.5 g each.
_CRACKER_PER_100G = NutritionFacts(calories=473.68, protein_g=7.9, carbs_g=63.2, fat_g=21.1)
_CRACKER_SERVING_G = 19.0
_TOPPABLES_CODE = "0066721029218"

#: The honest resolution: 4 pieces x 3.5 g = 14 g -> 66.3 kcal.
_EXPECTED_GRAMS = 14.0
_PIECE_ASSUMPTION = "estimated_common_portion:cracker cracker 3.5 g"


class _FakeFoodSource:
    """A scripted, network-free USDA stand-in keyed by normalized query."""

    def __init__(self, facts: dict[str, ProductFacts] | None = None) -> None:
        self._facts = facts or {}
        self.lookups: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    def lookup(self, query: str) -> ProductFacts | None:
        self.lookups.append(query)
        return self._facts.get(query.strip().lower())


class _FakeNameSource:
    """A scripted OFF name-search source returning one branded cracker product."""

    def __init__(self, *, description: str = "Christie Toppables Crackers") -> None:
        self._description = description
        self.queries: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    def search_by_name(self, query: str) -> tuple[ProductFacts, ...]:
        self.queries.append(query)
        source_ref = f"open_food_facts:{_TOPPABLES_CODE}"
        return (
            ProductFacts(
                source=OFF_SOURCE,
                source_ref=source_ref,
                query_key=normalize_query(query),
                description=self._description,
                facts=_CRACKER_PER_100G,
                default_serving_g=_CRACKER_SERVING_G,
                content_hash=_content_hash(source_ref, _CRACKER_PER_100G),
                barcode=None,
            ),
        )


class _DisabledSearchProvider:
    """Search disabled, so the branded chain reaches the OFF name tier directly."""

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


def _cracker_row(name: str) -> ProductFacts:
    return ProductFacts(
        source=FDC_SOURCE,
        source_ref="usda_fdc:542229",
        query_key=name,
        description="Crackers, standard snack-type, regular",
        facts=_CRACKER_PER_100G,
        default_serving_g=_CRACKER_SERVING_G,
        content_hash="cracker-row-hash",
        barcode=None,
    )


def _parsed_food(
    *,
    name: str,
    unit: str | None,
    amount: float,
    quantity_text: str,
    brand: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "type": "food",
        "name": name,
        "quantity_text": quantity_text,
        "unit": unit,
        "amount": amount,
    }
    if brand is not None:
        item["brand"] = brand
    return item


def _parse_provider(item: dict[str, Any]) -> FakeProvider:
    return FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": [item]}]
        * SELF_CONSISTENCY_FIRST_WINDOW
    )


def _product_path_pipeline(
    session: Session,
    *,
    item: dict[str, Any],
    food_source: _FakeFoodSource,
    mode: EstimatorClarifyMode = "estimate_first",
) -> Pipeline:
    """Parse + food resolution only: the ``food_step._build_item`` product path."""

    return Pipeline(
        [
            ParseStep(_parse_provider(item), policy=ParsePolicySettings(mode=mode)),
            FoodResolveStep(FoodResolver(session=session, source=food_source), clarify_mode=mode),
        ]
    )


def _off_name_pipeline(
    session: Session,
    *,
    item: dict[str, Any],
    off_source: _FakeNameSource,
    mode: EstimatorClarifyMode = "estimate_first",
) -> Pipeline:
    """Parse + food + official steps: the shared ``resolved_item._build_item`` path.

    USDA misses, official search is disabled, so the branded candidate resolves at
    the rank-3 ``product_database`` (OFF name search) tier — the path the reported
    smoke item took.
    """

    official_step = OfficialSourceResolveStep(
        provider=FakeProvider(responses=[]),
        search_provider=_DisabledSearchProvider(),
        fetch_settings=OfficialFetchSettings(allowed_hosts=frozenset({"example.com"})),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=_unused_fetch,
        reference_fetch_fn=_unused_fetch,
        off_name_resolver=OffNameResolver(session=session, source=off_source),
        clarify_mode=mode,
    )
    return Pipeline(
        [
            ParseStep(_parse_provider(item), policy=ParsePolicySettings(mode=mode)),
            FoodResolveStep(
                FoodResolver(session=session, source=_FakeFoodSource()), clarify_mode=mode
            ),
            official_step,
        ]
    )


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


def _assert_four_crackers(food: DerivedFoodItem, evidence: EvidenceSource) -> None:
    """The honest per-piece resolution, on the source's own trusted facts."""

    assert food.status == DerivedItemStatus.RESOLVED
    assert food.grams == pytest.approx(_EXPECTED_GRAMS)
    assert food.grams is not None and food.grams <= 25.0
    assert food.calories is not None
    assert 40.0 <= food.calories <= 130.0  # never the reported 360 kcal
    assert food.calories == pytest.approx(66.3)
    # The trusted facts survive: the per-100g snapshot is the row's own, unchanged.
    assert evidence.calories_per_100g == pytest.approx(473.68)
    assert _PIECE_ASSUMPTION in tuple(evidence.assumptions or ())


# ---------------------------------------------------------------------------
# Site 1: food_step._build_item (product path)
# ---------------------------------------------------------------------------


def test_four_crackers_on_the_product_path_cost_four_pieces(
    client: TestClient, session: Session
) -> None:
    user_id, event_id = _seed_event(client, "fty437-product@example.com", "4 crackers")
    food_source = _FakeFoodSource({"crackers": _cracker_row("crackers")})
    pipeline = _product_path_pipeline(
        session,
        item=_parsed_food(name="crackers", unit="crackers", amount=4, quantity_text="4 crackers"),
        food_source=food_source,
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    food = _foods(session, event_id)[0]
    evidence = _evidence(session, event_id)
    _assert_four_crackers(food, evidence)
    # It still resolves at its own tier — never demoted to a coarse prior.
    assert evidence.source_type == FDC_SOURCE_TYPE
    assert evidence.source_ref == "usda_fdc:542229"
    assert evidence.product_id is not None


def test_a_serving_count_of_the_same_product_is_unchanged(
    client: TestClient, session: Session
) -> None:
    """A serving-equivalent count is exactly what the default serving size is for."""

    user_id, event_id = _seed_event(client, "fty437-serving@example.com", "1 serving of crackers")
    food_source = _FakeFoodSource({"crackers": _cracker_row("crackers")})
    pipeline = _product_path_pipeline(
        session,
        item=_parsed_food(name="crackers", unit="serving", amount=1, quantity_text="1 serving"),
        food_source=food_source,
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    food = _foods(session, event_id)[0]
    assert food.grams == pytest.approx(_CRACKER_SERVING_G)
    assert food.calories == pytest.approx(90.0)
    assert not any(
        assumption.startswith("estimated_common_portion")
        for assumption in tuple(_evidence(session, event_id).assumptions or ())
    )


def test_two_servings_scale_the_serving_size(client: TestClient, session: Session) -> None:
    user_id, event_id = _seed_event(client, "fty437-two-servings@example.com", "2 servings")
    food_source = _FakeFoodSource({"crackers": _cracker_row("crackers")})
    pipeline = _product_path_pipeline(
        session,
        item=_parsed_food(name="crackers", unit="servings", amount=2, quantity_text="2 servings"),
        food_source=food_source,
    )

    process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    food = _foods(session, event_id)[0]
    assert food.grams == pytest.approx(2 * _CRACKER_SERVING_G)


# ---------------------------------------------------------------------------
# Site 2: resolved_item._build_item (the shared tier builder, OFF name tier)
# ---------------------------------------------------------------------------


def _branded_cracker_item() -> dict[str, Any]:
    return _parsed_food(
        name="toppables crackers",
        unit="crackers",
        amount=4,
        quantity_text="4 crackers",
        brand="Christie",
    )


def test_four_crackers_on_the_off_name_tier_cost_four_pieces(
    client: TestClient, session: Session
) -> None:
    """The reported path: the OFF row is kept, only its serving math is fixed."""

    user_id, event_id = _seed_event(client, "fty437-off-name@example.com", "4 toppables crackers")
    off_source = _FakeNameSource()
    pipeline = _off_name_pipeline(session, item=_branded_cracker_item(), off_source=off_source)

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    food = _foods(session, event_id)[0]
    evidence = _evidence(session, event_id)
    _assert_four_crackers(food, evidence)
    # The branded product row still backs the item: no fall-through to the coarse
    # model-prior density, which would drop the trusted facts.
    assert evidence.source_type == OFF_SOURCE_TYPE
    assert evidence.source_ref == f"open_food_facts:{_TOPPABLES_CODE}"
    assert off_source.queries


@pytest.mark.parametrize("mode", ["estimate_first", "balanced", "strict"])
def test_four_crackers_never_clarify_in_any_clarify_mode(
    client: TestClient, session: Session, mode: EstimatorClarifyMode
) -> None:
    """Never-fail by construction: the piece count is table-resolvable, so it can
    never reach the ``unresolvable_quantity`` branch in any policy mode."""

    user_id, event_id = _seed_event(client, f"fty437-{mode}@example.com", "4 toppables crackers")
    pipeline = _off_name_pipeline(
        session, item=_branded_cracker_item(), off_source=_FakeNameSource(), mode=mode
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []
    food = _foods(session, event_id)[0]
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.grams == pytest.approx(_EXPECTED_GRAMS)


def test_an_amountless_branded_snack_still_assumes_one_serving(
    client: TestClient, session: Session
) -> None:
    """The piece carve-out is about *counts*: "some toppables crackers" states none,
    so the default-serving assumption still applies (one serving, 19 g)."""

    user_id, event_id = _seed_event(client, "fty437-amountless@example.com", "toppables crackers")
    item = _parsed_food(
        name="toppables crackers", unit=None, amount=0, quantity_text="", brand="Christie"
    )
    item["amount"] = None
    pipeline = _off_name_pipeline(session, item=item, off_source=_FakeNameSource())

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    food = _foods(session, event_id)[0]
    assert food.grams == pytest.approx(_CRACKER_SERVING_G)
    assert "estimated_default_serving" in tuple(_evidence(session, event_id).assumptions or ())
