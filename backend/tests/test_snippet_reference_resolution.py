"""FTY-314 acceptance tests: search-result snippets as bounded nutrition evidence.

Drive the real parse → food → official/reference pipeline with network-free fakes,
proving the Toppables/PC-hummus dogfood audit scenarios: when the result page fetch
fails (HTTP 403) or returns a JavaScript shell with no facts, the resolver extracts
from the candidate's bounded title+snippet instead — schema-validated, count/serving
math still deterministic, provenance still the result URL plus an explicit
``search_result_snippet`` label, and the raw snippet never persisted anywhere.
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
from app.estimator.hardened_fetch import FetchResponseError
from app.estimator.official_fetch import OfficialFetchSettings
from app.estimator.processing import process_estimation
from app.estimator.search import SearchCandidate, SearchResult, SearchStatus
from app.estimator.searched_reference import REFERENCE_SOURCE, REFERENCE_SOURCE_TYPE
from app.models.estimation import EstimationRun
from tests.test_official_source_resolution import (
    FakeFoodSource,
    FakeSearchProvider,
    RecordingFetcher,
    _evidence,
    _foods,
    _pipeline,
    _questions,
    _seed_event,
)

#: A marker embedded in every fake snippet, asserted absent from everything
#: persisted — raw snippet text must never be retained.
_RAW_SNIPPET_SENTINEL = "RAW-SNIPPET-SENTINEL"

_TOPPABLES_URL = "https://reference.example.com/toppables-crackers"
_TOPPABLES_SNIPPET = (
    f"{_RAW_SNIPPET_SENTINEL} Serving Size Per 5 crackers (19 g). "
    "Calories 90. Fat 3.5 g. Carbs 13 g. Protein 1 g."
)
_TOPPABLES_SNIPPET_FACTS = {
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

_HUMMUS_URL = "https://reference.example.com/pc-dill-pickle-hummus"
_HUMMUS_SNIPPET = (
    f"{_RAW_SNIPPET_SENTINEL} Serving Size Per 30 g. Calories 80. Fat 6 g. Carbs 4 g. Protein 2 g."
)
_HUMMUS_SNIPPET_FACTS = {
    "basis": "per_serving",
    "product_name": "PC Dill Pickle Hummus",
    "calories": 80.0,
    "protein_g": 2.0,
    "carbs_g": 4.0,
    "fat_g": 6.0,
    "serving_size_amount": 30.0,
    "serving_size_unit": "g",
}


class ForbiddenFetcher:
    """A network-free fetch seam that always fails with HTTP 403."""

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def __call__(self, url: str, settings: object) -> str:
        self.fetched.append(url)
        raise FetchResponseError("fetch returned HTTP 403", status_code=403)


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


def _snippet_result(url: str, title: str, snippet: str) -> SearchResult:
    return SearchResult(
        status=SearchStatus.SUCCESS,
        candidates=(SearchCandidate(url=url, title=title, snippet=snippet),),
    )


def _run(session: Session, event_id: uuid.UUID) -> EstimationRun:
    return session.scalars(
        select(EstimationRun).where(EstimationRun.log_event_id == event_id)
    ).one()


def _assert_no_raw_snippet_persisted(session: Session, event_id: uuid.UUID) -> None:
    run = _run(session, event_id)
    persisted = (
        f"{run.trace!r} {run.assumptions!r} {run.source_refs!r} "
        f"{run.validation_errors!r} {run.error!r}"
    )
    assert _RAW_SNIPPET_SENTINEL not in persisted
    evidence = _evidence(session, event_id)
    assert _RAW_SNIPPET_SENTINEL not in f"{evidence.source_ref!r} {evidence.assumptions!r}"


def test_toppables_crackers_resolve_from_snippet_when_fetch_is_403(
    client: TestClient, session: Session
) -> None:
    # Acceptance: `4 crackers` against a snippet stating `per 5 crackers (19 g),
    # 90 kcal` scales to ~72 kcal (FTY-252 count math) with reference_source
    # provenance and the snippet-derived label — never four whole servings.
    user_id, event_id = _seed_event(client, "fty314-toppables@example.com", "4 crackers")
    search = FakeSearchProvider(
        _snippet_result(_TOPPABLES_URL, "Toppables Crackers | Nutrition", _TOPPABLES_SNIPPET)
    )
    reference_fetcher = ForbiddenFetcher()
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),  # USDA miss
        parsed_item={
            "type": "food",
            "name": "crackers",
            "brand": "Toppables",
            "quantity_text": "4",
            "unit": "crackers",
            "amount": 4,
        },
        search_provider=search,
        fetcher=RecordingFetcher(),
        # Official fetch unconfigured: the branded item goes straight to the
        # reference tier, whose page fetch then 403s.
        fetch_settings=OfficialFetchSettings(),
        reference_fetcher=reference_fetcher,  # type: ignore[arg-type]
        estimates=[
            {"disposition": "resolved", "confidence": 0.9, "facts": _TOPPABLES_SNIPPET_FACTS}
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    assert _questions(session, event_id) == []

    foods = _foods(session, event_id)
    assert len(foods) == 1
    item = foods[0]
    assert item.status == DerivedItemStatus.RESOLVED
    assert item.calories == pytest.approx(72.0)  # 90 × 4/5, never 4 × 90
    assert item.grams == pytest.approx(15.2)  # 19 g × 4/5
    assert item.protein_g == pytest.approx(0.8)
    assert item.carbs_g == pytest.approx(10.4)
    assert item.fat_g == pytest.approx(2.8)

    evidence = _evidence(session, event_id)
    assert evidence.source_type == REFERENCE_SOURCE_TYPE
    assert evidence.source_ref == f"{REFERENCE_SOURCE_TYPE}:{_TOPPABLES_URL}"
    assert "search_result_snippet" in (evidence.assumptions or [])
    assert evidence.product_id is None

    run = _run(session, event_id)
    assert REFERENCE_SOURCE in run.source_refs
    # The page fetch was attempted first (fetch-first order preserved).
    assert reference_fetcher.fetched == [_TOPPABLES_URL]
    assert search.queries == ["crackers Toppables nutrition facts"]
    _assert_no_raw_snippet_persisted(session, event_id)


def test_pc_hummus_tbsp_resolves_as_hummus_not_pickles(
    client: TestClient, session: Session
) -> None:
    # Acceptance: a PC dill pickle hummus snippet (`per 30 g, 80 kcal`) resolves
    # `1 tbsp` (≈15 g) to ~40 kcal — a plausible hummus amount, not ~2 kcal pickles.
    user_id, event_id = _seed_event(client, "fty314-hummus@example.com", "1 tbsp of hummus")
    search = FakeSearchProvider(
        _snippet_result(_HUMMUS_URL, "PC Dill Pickle Hummus", _HUMMUS_SNIPPET)
    )
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item={
            "type": "food",
            "name": "dill pickle hummus",
            "brand": "PC",
            "quantity_text": "1 tbsp",
            "unit": "tbsp",
            "amount": 1,
        },
        search_provider=search,
        fetcher=RecordingFetcher(),
        fetch_settings=OfficialFetchSettings(),
        reference_fetcher=ForbiddenFetcher(),  # type: ignore[arg-type]
        estimates=[{"disposition": "resolved", "confidence": 0.9, "facts": _HUMMUS_SNIPPET_FACTS}],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED

    foods = _foods(session, event_id)
    assert len(foods) == 1
    item = foods[0]
    assert item.status == DerivedItemStatus.RESOLVED
    assert item.grams == pytest.approx(15.0)  # 1 tbsp, measured — not a 30 g serving
    assert item.calories == pytest.approx(40.0)  # 80/30 g × 15 g
    assert item.calories is not None
    assert item.calories > 20.0  # unmistakably hummus-scale, not 2 kcal pickles

    evidence = _evidence(session, event_id)
    assert evidence.source_type == REFERENCE_SOURCE_TYPE
    assert evidence.source_ref == f"{REFERENCE_SOURCE_TYPE}:{_HUMMUS_URL}"
    assert "search_result_snippet" in (evidence.assumptions or [])
    _assert_no_raw_snippet_persisted(session, event_id)


def test_snippet_rescues_a_javascript_shell_page(client: TestClient, session: Session) -> None:
    # Acceptance: the fetch succeeds but returns sanitized shell text with no
    # nutrition facts; the resolver still uses the compatible snippet from the
    # same candidate (page extraction first, snippet second).
    user_id, event_id = _seed_event(client, "fty314-shell@example.com", "1 tbsp of hummus")
    search = FakeSearchProvider(
        _snippet_result(_HUMMUS_URL, "PC Dill Pickle Hummus", _HUMMUS_SNIPPET)
    )
    shell_fetcher = RecordingFetcher(text="Please enable JavaScript to view this page.")
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item={
            "type": "food",
            "name": "dill pickle hummus",
            "quantity_text": "1 tbsp",
            "unit": "tbsp",
            "amount": 1,
        },
        search_provider=search,
        fetcher=RecordingFetcher(),
        reference_fetcher=shell_fetcher,
        estimates=[
            # The shell page carries no facts → unresolved; the snippet resolves.
            {"disposition": "unresolved", "confidence": 0.1},
            {"disposition": "resolved", "confidence": 0.9, "facts": _HUMMUS_SNIPPET_FACTS},
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    item = _foods(session, event_id)[0]
    assert item.status == DerivedItemStatus.RESOLVED
    assert item.calories == pytest.approx(40.0)

    evidence = _evidence(session, event_id)
    assert evidence.source_type == REFERENCE_SOURCE_TYPE
    assert "search_result_snippet" in (evidence.assumptions or [])
    assert shell_fetcher.fetched == [_HUMMUS_URL]
    _assert_no_raw_snippet_persisted(session, event_id)


def test_snippetless_candidate_preserves_fetch_first_fallthrough(
    client: TestClient, session: Session
) -> None:
    # Acceptance: an empty/missing snippet preserves the existing behavior — a
    # failed fetch exhausts the candidate and the resolver falls through to the
    # model prior with per-tier reasons, with no snippet extraction call.
    user_id, event_id = _seed_event(client, "fty314-nosnippet@example.com", "1 tbsp of hummus")
    search = FakeSearchProvider(
        SearchResult(
            status=SearchStatus.SUCCESS,
            candidates=(SearchCandidate(url=_HUMMUS_URL, title="PC Dill Pickle Hummus"),),
        )
    )
    model_prior_facts: dict[str, Any] = {
        "basis": "per_100g",
        "product_name": "hummus",
        "calories": 170.0,
        "protein_g": 7.0,
        "carbs_g": 14.0,
        "fat_g": 10.0,
    }
    pipeline = _pipeline(
        session,
        food_source=FakeFoodSource({}),
        parsed_item={
            "type": "food",
            "name": "dill pickle hummus",
            "quantity_text": "1 tbsp",
            "unit": "tbsp",
            "amount": 1,
        },
        search_provider=search,
        fetcher=RecordingFetcher(),
        fetch_settings=OfficialFetchSettings(),
        reference_fetcher=ForbiddenFetcher(),  # type: ignore[arg-type]
        # Exactly one scripted response: the model prior. A snippet extraction
        # attempt would consume it and fail the run.
        estimates=[{"disposition": "resolved", "confidence": 0.8, "facts": model_prior_facts}],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    item = _foods(session, event_id)[0]
    assert item.status == DerivedItemStatus.RESOLVED

    evidence = _evidence(session, event_id)
    assert evidence.source_type == "model_prior"
    assert "search_result_snippet" not in (evidence.assumptions or [])
