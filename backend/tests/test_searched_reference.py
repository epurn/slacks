"""Focused tests for the shared searched-reference → per-100g primitive (FTY-283)."""

from __future__ import annotations

from typing import Any

import pytest

from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    SearchCandidate,
    SearchCapability,
    SearchResult,
    SearchStatus,
)
from app.estimator.searched_reference import (
    _REFERENCE_PAGE_KIND,
    MAX_SOURCE_REF_LEN,
    REFERENCE_SOURCE_TYPE,
    searched_reference_per_100g,
)
from app.llm.providers.fake import FakeProvider


class FakeSearchProvider:
    """A scripted, network-free search provider recording the query."""

    def __init__(self, result: SearchResult) -> None:
        self._result = result
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
            id="fake",
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=("named_product",),
            enabled=True,
            available=True,
        )

    def search(self, query: str) -> SearchResult:
        self.queries.append(query)
        return self._result


class RecordingFetcher:
    """Network-free searched-result fetch seam."""

    def __init__(self, pages: dict[str, str]) -> None:
        self._pages = pages
        self.fetched: list[str] = []

    def __call__(self, url: str) -> str | None:
        self.fetched.append(url)
        return self._pages.get(url)


def _estimate(
    *,
    confidence: float = 0.9,
    calories: float = 120.0,
    serving_size_amount: float = 60.0,
) -> dict[str, Any]:
    return {
        "disposition": "resolved",
        "confidence": confidence,
        "facts": {
            "basis": "per_serving",
            "calories": calories,
            "protein_g": 6.0,
            "carbs_g": 18.0,
            "fat_g": 3.0,
            "serving_size_amount": serving_size_amount,
            "serving_size_unit": "g",
        },
        "assumptions": ["source states one wrap serving"],
    }


def test_primitive_skips_bad_candidates_and_returns_plausible_per_100g_facts() -> None:
    overlong = "https://example.com/" + ("x" * MAX_SOURCE_REF_LEN)
    low_confidence = "https://example.com/low"
    implausible = "https://example.com/implausible"
    good = "https://example.com/good"
    search = FakeSearchProvider(
        SearchResult(
            status=SearchStatus.SUCCESS,
            candidates=(
                SearchCandidate(url=overlong, title="too long"),
                SearchCandidate(url=low_confidence, title="low confidence"),
                SearchCandidate(url=implausible, title="kj read as kcal"),
                SearchCandidate(url=good, title="good"),
            ),
        )
    )
    fetcher = RecordingFetcher(
        {
            low_confidence: "low confidence page",
            implausible: "implausible page",
            good: "good page",
        }
    )
    before_fetch: list[str] = []
    provider = FakeProvider(
        responses=[
            _estimate(confidence=0.2),
            _estimate(calories=950.0, serving_size_amount=100.0),
            _estimate(),
        ]
    )

    found = searched_reference_per_100g(
        provider=provider,
        search_provider=search,
        fetch=fetcher,
        query="sobeys wrap nutrition facts",
        page_kind=_REFERENCE_PAGE_KIND,
        source_type=REFERENCE_SOURCE_TYPE,
        before_fetch=before_fetch.append,
    )

    assert found is not None
    assert found.source_ref == f"{REFERENCE_SOURCE_TYPE}:{good}"
    assert found.hash_key == good
    assert found.default_serving_g == 60.0
    assert found.facts.calories == pytest.approx(200.0)
    assert found.facts.protein_g == pytest.approx(10.0)
    assert found.facts.carbs_g == pytest.approx(30.0)
    assert found.facts.fat_g == pytest.approx(5.0)
    assert found.assumptions == ("source states one wrap serving",)
    assert search.queries == ["sobeys wrap nutrition facts"]
    assert fetcher.fetched == [low_confidence, implausible, good]
    assert before_fetch == [
        f"{REFERENCE_SOURCE_TYPE}:{low_confidence}",
        f"{REFERENCE_SOURCE_TYPE}:{implausible}",
        f"{REFERENCE_SOURCE_TYPE}:{good}",
    ]
