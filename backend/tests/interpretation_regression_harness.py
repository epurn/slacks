"""Shared network-free seams for the FTY-327 interpretation-overhaul regression.

A focused sibling to the FTY-302 ``estimate_first_representative_harness`` that,
unlike it, leaves the web-evidence **search enabled**: these seams drive the real
parse -> interpretation-session -> food-resolution -> official/reference/model-prior
pipeline through the production worker entrypoint, faking only the external
provider/search/fetch boundaries so CI never spends tokens or opens sockets.

Fixture nutrition facts are synthetic and labelled model-prior/reference; the raw
snippet text carries a sentinel the tests assert is never persisted.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.estimator.fdc import ProductFacts
from app.estimator.food_step import FoodResolver, FoodResolveStep
from app.estimator.hardened_fetch import FetchResponseError
from app.estimator.official_fetch import OfficialFetchSettings
from app.estimator.official_step import OfficialSourceResolveStep
from app.estimator.parse import ParseStep
from app.estimator.parse_policy import ParsePolicySettings
from app.estimator.pipeline import Pipeline
from app.estimator.reference_fetch import ReferenceFetchSettings
from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    SearchCandidate,
    SearchCapability,
    SearchResult,
    SearchStatus,
)
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.errors import LLMError
from app.llm.providers.fake import FakeProvider
from app.models.derived import ClarificationQuestion, DerivedFoodItem
from app.models.estimation import EstimationRun
from app.models.food_sources import EvidenceSource, Product
from app.settings import EstimatorClarifyMode

#: A marker embedded in every fake snippet, asserted absent from everything
#: persisted — raw snippet text must never be retained (data-retention.md).
RAW_SNIPPET_SENTINEL = "RAW-SNIPPET-SENTINEL"

TOPPABLES_URL = "https://reference.example.com/toppables-crackers"
TOPPABLES_SNIPPET = (
    f"{RAW_SNIPPET_SENTINEL} Serving Size Per 5 crackers (19 g). "
    "Calories 90. Fat 3.5 g. Carbs 13 g. Protein 1 g."
)
#: Toppables facts per counted serving ``5 crackers (19 g)`` (FTY-252).
TOPPABLES_SNIPPET_FACTS = {
    "basis": "per_serving",
    "product_name": "Toppables crackers",
    "calories": 90.0,
    "protein_g": 1.0,
    "carbs_g": 13.0,
    "fat_g": 3.5,
    "serving_size_amount": 19.0,
    "serving_size_unit": "g",
    "serving_count": {"amount": 5.0, "unit": "crackers"},
}

HUMMUS_URL = "https://reference.example.com/pc-dill-pickle-hummus"
HUMMUS_SNIPPET = (
    f"{RAW_SNIPPET_SENTINEL} Serving Size Per 30 g. Calories 80. Fat 6 g. Carbs 4 g. Protein 2 g."
)
#: PC dill pickle hummus facts per 30 g.
HUMMUS_SNIPPET_FACTS = {
    "basis": "per_serving",
    "product_name": "PC Dill Pickle Hummus",
    "calories": 80.0,
    "protein_g": 2.0,
    "carbs_g": 4.0,
    "fat_g": 6.0,
    "serving_size_amount": 30.0,
    "serving_size_unit": "g",
}

CRACKER_SNIPPET_ESTIMATE: dict[str, Any] = {
    "disposition": "resolved",
    "confidence": 0.9,
    "facts": TOPPABLES_SNIPPET_FACTS,
}
HUMMUS_SNIPPET_ESTIMATE: dict[str, Any] = {
    "disposition": "resolved",
    "confidence": 0.9,
    "facts": HUMMUS_SNIPPET_FACTS,
}


class MissingFoodSource:
    """A network-free USDA/OFF stand-in that intentionally misses every query."""

    def __init__(self) -> None:
        self.lookups: list[str] = []

    @property
    def enabled(self) -> bool:
        return True

    def lookup(self, query: str) -> ProductFacts | None:
        self.lookups.append(query)
        return None


class KeyedSnippetSearchProvider:
    """An *enabled* search seam routing each query by keyword, like a real engine.

    Rules are ordered ``(keyword, result)`` pairs matched against the lower-cased
    query; an unmatched query returns no results. Queries are recorded so tests can
    assert exactly what identity text egressed.
    """

    def __init__(self, rules: tuple[tuple[str, SearchResult], ...]) -> None:
        self._rules = rules
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
        lowered = query.casefold()
        for keyword, result in self._rules:
            if keyword in lowered:
                return result
        return SearchResult(status=SearchStatus.PARTIAL)


class CyclingFailFetcher:
    """A result-page fetch that always fails, cycling 403/405/460 across calls."""

    _CODES = (403, 405, 460)

    def __init__(self) -> None:
        self.fetched: list[str] = []
        self.status_codes: list[int] = []

    def __call__(self, url: str, settings: object) -> str:
        code = self._CODES[len(self.fetched) % len(self._CODES)]
        self.fetched.append(url)
        self.status_codes.append(code)
        raise FetchResponseError(f"fetch returned HTTP {code}", status_code=code)


class ForbiddenFetcher:
    """A result-page fetch that always fails HTTP 403 (the audited page block)."""

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def __call__(self, url: str, settings: object) -> str:
        self.fetched.append(url)
        raise FetchResponseError("fetch returned HTTP 403", status_code=403)


def no_official_fetch(url: str, settings: object) -> str:
    raise AssertionError(f"official fetch must not run (tier unconfigured): {url}")


def snippet_result(url: str, title: str, snippet: str) -> SearchResult:
    return SearchResult(
        status=SearchStatus.SUCCESS,
        candidates=(SearchCandidate(url=url, title=title, snippet=snippet),),
    )


def snack_search_provider() -> KeyedSnippetSearchProvider:
    """A keyed engine: crackers (``toppab``) and hummus (``dill``) each hit a page."""

    return KeyedSnippetSearchProvider(
        (
            (
                "toppab",
                snippet_result(TOPPABLES_URL, "Toppables Crackers | Nutrition", TOPPABLES_SNIPPET),
            ),
            ("dill", snippet_result(HUMMUS_URL, "PC Dill Pickle Hummus", HUMMUS_SNIPPET)),
        )
    )


def seed_event(client: TestClient, email: str, raw_text: str) -> tuple[uuid.UUID, uuid.UUID, str]:
    """Create a real user-owned log event through the local API."""

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
    return user_id, uuid.UUID(created.json()["id"]), auth


def build_pipeline(
    session: Session,
    *,
    parse_samples: list[dict[str, Any] | LLMError],
    estimates: list[dict[str, Any] | LLMError],
    search: KeyedSnippetSearchProvider,
    reference_fetcher: CyclingFailFetcher | ForbiddenFetcher,
    mode: EstimatorClarifyMode = "estimate_first",
) -> Pipeline:
    """The real parse -> food -> official/reference pipeline with network seams faked.

    The official-fetch allowlist is left unconfigured (matching the audited
    deployment): branded candidates skip the official tier and reach the
    search-enabled reference tier, whose result-page fetch then fails — forcing
    the FTY-314 snippet fallback, and on the dead-end path the model prior.
    """

    parse_provider = FakeProvider(responses=parse_samples * SELF_CONSISTENCY_FIRST_WINDOW)
    resolver = FoodResolver(session=session, source=MissingFoodSource())
    official_step = OfficialSourceResolveStep(
        provider=FakeProvider(responses=estimates),
        search_provider=search,
        fetch_settings=OfficialFetchSettings(),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=no_official_fetch,
        reference_fetch_fn=reference_fetcher,
        clarify_mode=mode,
    )
    return Pipeline(
        [
            ParseStep(parse_provider, policy=ParsePolicySettings(mode=mode)),
            FoodResolveStep(resolver, clarify_mode=mode),
            official_step,
        ]
    )


def foods(session: Session, event_id: uuid.UUID) -> list[DerivedFoodItem]:
    return list(
        session.scalars(select(DerivedFoodItem).where(DerivedFoodItem.log_event_id == event_id))
    )


def evidence_for(session: Session, food: DerivedFoodItem) -> EvidenceSource:
    return session.scalars(
        select(EvidenceSource).where(EvidenceSource.derived_food_item_id == food.id)
    ).one()


def questions(session: Session, event_id: uuid.UUID) -> list[ClarificationQuestion]:
    return list(
        session.scalars(
            select(ClarificationQuestion).where(ClarificationQuestion.log_event_id == event_id)
        )
    )


def run_for(session: Session, event_id: uuid.UUID) -> EstimationRun:
    return session.scalars(
        select(EstimationRun).where(EstimationRun.log_event_id == event_id)
    ).one()


def persisted_text(session: Session, event_id: uuid.UUID) -> str:
    """Everything the run persisted beyond the raw event, as one searchable string."""

    run = run_for(session, event_id)
    parts = [
        f"{run.trace!r} {run.assumptions!r} {run.source_refs!r} "
        f"{run.validation_errors!r} {run.error!r}"
    ]
    for food in foods(session, event_id):
        evidence = session.scalars(
            select(EvidenceSource).where(EvidenceSource.derived_food_item_id == food.id)
        ).one_or_none()
        if evidence is not None:
            parts.append(f"{evidence.source_ref!r} {evidence.assumptions!r}")
    parts.extend(
        f"{question.question_text!r} {question.options!r}"
        for question in questions(session, event_id)
    )
    parts.extend(f"{product.description!r}" for product in session.scalars(select(Product)))
    return " ".join(parts)


def hypothesis_entries(trace: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The sanitized ``hypothesis_revision`` trace entries the session emitted."""

    return [entry for entry in (trace or []) if entry.get("decision") == "hypothesis_revision"]


def per_candidate_hypothesis_entries(trace: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [entry for entry in hypothesis_entries(trace) if "candidate_index" in entry]


def parsed_sample(items: list[dict[str, Any]], *, confidence: float = 0.93) -> dict[str, Any]:
    return {"disposition": "parsed", "confidence": confidence, "items": items}


def cracker_item(
    *, quantity_text: str, amount: float, brand: str, unit: str = "crackers"
) -> dict[str, Any]:
    return {
        "type": "food",
        "name": "crackers",
        "brand": brand,
        "quantity_text": quantity_text,
        "unit": unit,
        "amount": amount,
    }


def hummus_item(*, quantity_text: str, amount: float, brand: str) -> dict[str, Any]:
    return {
        "type": "food",
        "name": "dill pickle hummus",
        "brand": brand,
        "quantity_text": quantity_text,
        "unit": "tbsp",
        "amount": amount,
    }


def model_prior_estimate(
    calories: float, protein: float, carbs: float, fat: float, assumption: str
) -> dict[str, Any]:
    return {
        "disposition": "resolved",
        "confidence": 0.85,
        "facts": {
            "basis": "as_logged",
            "calories": calories,
            "protein_g": protein,
            "carbs_g": carbs,
            "fat_g": fat,
        },
        "assumptions": [assumption],
    }
