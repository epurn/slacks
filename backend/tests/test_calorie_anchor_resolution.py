"""End-to-end tests for explicit calorie anchors + no-silent-drop (FTY-419).

Drive :func:`app.estimator.processing.process_estimation` with a real ``ParseStep``
+ ``UserTextResolveStep`` + ``FoodResolveStep`` (all network seams faked) against the
migrated database, proving the acceptance criteria:

- the dogfood repro "half a 300 calorie sub bun with mustard, mozzarella and turkey"
  logs an entry containing **the bun** plus the other items — no described item is
  silently dropped;
- an explicit calorie anchor **hard-overrides** an independent estimate and respects
  the quantity modifier: "half a 300 calorie sub bun" (``amount = 0.5``) resolves to
  ``300 × 0.5 = 150`` kcal, and "2×" doubles it;
- an anchored item still carries **estimated** macros (not null), scaled consistently
  with the anchored calories;
- a described food that cannot be resolved is persisted as an honest editable item,
  never a vanished one.
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
from app.enums import (
    DerivedItemStatus,
    EstimationJobStatus,
    LogEventStatus,
    SourceType,
)
from app.estimator.food_resolvers import FoodResolver
from app.estimator.food_step import FoodResolveStep
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
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.estimator.user_text_macro_estimator import UserTextMacroEstimator
from app.estimator.user_text_step import UserTextResolveStep
from app.llm.providers.fake import FakeProvider
from app.models.derived import DerivedFoodItem
from app.models.food_sources import EvidenceSource

_REFERENCE_URL = "https://nutrition-reference.example.com/foods/bun"

_SUB_BUN_TEXT = "half a 300 calorie sub bun with mustard, mozzarella and turkey"


# --- fakes (network-free) ---------------------------------------------------------


class DisabledFoodSource:
    """A generic-food source that is switched off (no FDC key)."""

    enabled = False

    def lookup(self, query: str) -> None:  # pragma: no cover - never called
        raise AssertionError("disabled source must not be queried")


class FakeSearchProvider:
    """A scripted, network-free :class:`SearchProvider`."""

    def __init__(self, result: SearchResult, *, available: bool = True) -> None:
        self._result = result
        self._available = available
        self.queries: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    @property
    def available(self) -> bool:
        return self._available

    @property
    def capability(self) -> SearchCapability:
        return SearchCapability(
            id="official_source",
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=("named_product",),
            enabled=True,
            available=self._available,
        )

    def search(self, query: str) -> SearchResult:
        self.queries.append(query)
        return self._result


class RecordingFetcher:
    """A network-free page fetcher recording the URLs it is handed."""

    def __init__(self, text: str) -> None:
        self._text = text
        self.fetched: list[str] = []

    def __call__(self, url: str, settings: object) -> str:
        self.fetched.append(url)
        return self._text


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _food_item(
    name: str,
    *,
    amount: float | None = None,
    unit: str | None = None,
    quantity_text: str = "",
    stated_calories: float | None = None,
    stated_protein_g: float | None = None,
) -> dict[str, object]:
    item: dict[str, object] = {"type": "food", "name": name, "quantity_text": quantity_text}
    if amount is not None:
        item["amount"] = amount
    if unit is not None:
        item["unit"] = unit
    if stated_calories is not None:
        item["stated_calories"] = stated_calories
    if stated_protein_g is not None:
        item["stated_protein_g"] = stated_protein_g
    return item


def _pipeline(
    session: Session,
    *,
    parsed_items: list[dict[str, object]],
    macro_estimator: UserTextMacroEstimator | None = None,
    samples: int = SELF_CONSISTENCY_FIRST_WINDOW,
) -> Pipeline:
    """Real parse + user-text + food pipeline (generic source disabled), seams faked."""

    parse_provider = FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": parsed_items}] * samples
    )
    resolver = FoodResolver(session=session, source=DisabledFoodSource())
    return Pipeline(
        [
            ParseStep(parse_provider),
            UserTextResolveStep(macro_estimator=macro_estimator),
            FoodResolveStep(resolver),
        ]
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


def _foods(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    )


def _macro_estimator(
    *, search: FakeSearchProvider, estimates: list[dict[str, Any]], fetch_text: str
) -> UserTextMacroEstimator:
    return UserTextMacroEstimator(
        provider=FakeProvider(responses=list(estimates)),
        search_provider=search,
        reference_fetch_settings=ReferenceFetchSettings(),
        reference_fetch_fn=RecordingFetcher(text=fetch_text),
    )


# --- AC1: never drop a described item ---------------------------------------------


def test_multi_item_entry_keeps_every_described_item(client: TestClient, session: Session) -> None:
    # The dogfood repro: the bun (the item carrying the explicit anchor) must survive
    # alongside the three fillings — four described items, four persisted rows.
    user_id, event_id = _seed_event(client, "subbun@example.com", _SUB_BUN_TEXT)
    parsed = [
        _food_item("sub bun", amount=0.5, quantity_text="half", stated_calories=300.0),
        _food_item("mustard", quantity_text="some"),
        _food_item("mozzarella", quantity_text="some"),
        _food_item("turkey", quantity_text="some"),
    ]
    pipeline = _pipeline(session, parsed_items=parsed)

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)
    assert result.job_status is EstimationJobStatus.SUCCEEDED

    foods = _foods(session, event_id)
    names = {food.name for food in foods}
    assert names == {"sub bun", "mustard", "mozzarella", "turkey"}
    assert len(foods) == 4

    # The bun is present and carries the anchored calories, not a vanished item.
    bun = next(food for food in foods if food.name == "sub bun")
    assert bun.status == DerivedItemStatus.RESOLVED
    assert bun.calories == 150.0


# --- AC2: explicit calorie anchor hard-overrides + respects the quantity modifier ---


@pytest.mark.parametrize(
    ("amount", "quantity_text", "expected"),
    [
        (0.5, "half", 150.0),  # half a 300 calorie sub bun
        (2.0, "two", 600.0),  # 2× 300 calorie sub buns
        (1.0, "1", 300.0),  # one whole 300 calorie sub bun
    ],
)
def test_calorie_anchor_hard_overrides_and_respects_quantity(
    client: TestClient, session: Session, amount: float, quantity_text: str, expected: float
) -> None:
    user_id, event_id = _seed_event(
        client, f"anchor-{amount}@example.com", f"{quantity_text} 300 calorie sub bun"
    )
    parsed = [
        _food_item("sub bun", amount=amount, quantity_text=quantity_text, stated_calories=300.0)
    ]
    pipeline = _pipeline(session, parsed_items=parsed)

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)
    assert result.event_status is LogEventStatus.COMPLETED

    bun = _foods(session, event_id)[0]
    # The user's explicit anchor wins over any independent estimate, scaled by quantity.
    assert bun.calories == expected

    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).one()
    assert evidence.source_type == SourceType.USER_TEXT.value
    assert evidence.field_provenance is not None
    assert evidence.field_provenance["calories"] == "user_stated"
    if amount != 1.0:
        # A scaled anchor records honest, content-free provenance (numbers only).
        assert evidence.assumptions is not None
        assert any("calorie_anchor" in a for a in evidence.assumptions)
        assert _SUB_BUN_TEXT not in str(evidence.assumptions)


def test_measured_portion_calories_are_not_scaled(client: TestClient, session: Session) -> None:
    # "500 cals" against a measured 100 g portion is the as-logged total for that
    # amount, NOT a per-unit anchor to multiply — it must stay 500, never 50 000.
    user_id, event_id = _seed_event(client, "measured@example.com", "100 g chips 500 cals")
    parsed = [_food_item("chips", amount=100.0, unit="g", stated_calories=500.0)]
    pipeline = _pipeline(session, parsed_items=parsed)

    process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)
    assert _foods(session, event_id)[0].calories == 500.0


# --- AC3: an anchored item still carries estimated macros --------------------------


def test_anchored_item_still_has_estimated_macros(client: TestClient, session: Session) -> None:
    # The 150 kcal anchor still needs macros: they are estimated from a reference page
    # and scaled to the anchored (150) energy — not left null, and not scaled to 300.
    user_id, event_id = _seed_event(client, "anchormacros@example.com", "half a 300 cal sub bun")
    parsed = [_food_item("sub bun", amount=0.5, quantity_text="half", stated_calories=300.0)]
    search = FakeSearchProvider(
        SearchResult(
            status=SearchStatus.SUCCESS,
            candidates=(SearchCandidate(url=_REFERENCE_URL, title="sub bun nutrition"),),
        )
    )
    # Reference per-100g: 100 kcal / 8 P / 50 C / 3 F. Scaled to the 150 kcal anchor → ×1.5.
    facts = {
        "basis": "per_100g",
        "calories": 100.0,
        "protein_g": 8.0,
        "carbs_g": 50.0,
        "fat_g": 3.0,
    }
    estimator = _macro_estimator(
        search=search,
        estimates=[{"disposition": "resolved", "confidence": 0.9, "facts": facts}],
        fetch_text="sub bun 100 kcal/100g",
    )
    pipeline = _pipeline(session, parsed_items=parsed, macro_estimator=estimator)

    process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    bun = _foods(session, event_id)[0]
    assert bun.calories == 150.0
    # Macros present (not null) and consistent with the 150 kcal anchor (×1.5), proving
    # they were scaled to the anchored energy, not the unscaled 300.
    assert bun.protein_g == pytest.approx(12.0)  # 8 × 1.5
    assert bun.carbs_g == pytest.approx(75.0)  # 50 × 1.5
    assert bun.fat_g == pytest.approx(4.5)  # 3 × 1.5

    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).one()
    assert evidence.field_provenance == {
        "calories": "user_stated",
        "protein_g": "estimated",
        "carbs_g": "estimated",
        "fat_g": "estimated",
    }


# --- AC4: a described food that can't resolve is editable, never dropped -----------


def test_unresolvable_described_food_is_editable_not_dropped(
    client: TestClient, session: Session
) -> None:
    # No enabled source, no stated calories, no official/model-prior tier wired: the
    # described food must still be persisted as an honest editable item — never dropped.
    user_id, event_id = _seed_event(client, "editable@example.com", "some homemade mystery stew")
    parsed = [_food_item("homemade mystery stew", quantity_text="a bowl", amount=1.0)]
    pipeline = _pipeline(session, parsed_items=parsed)

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    foods = _foods(session, event_id)
    assert len(foods) == 1
    stew = foods[0]
    assert stew.name == "homemade mystery stew"
    # Present and editable (unresolved), not a vanished item; the event still completes.
    assert stew.status == DerivedItemStatus.UNRESOLVED
    assert result.event_status is LogEventStatus.COMPLETED
