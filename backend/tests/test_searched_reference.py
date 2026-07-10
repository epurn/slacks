"""Focused tests for the shared searched-reference → per-100g primitive (FTY-283)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.estimator.pipeline import CandidateDraft, EstimationContext
from app.estimator.reference_fetch import ReferenceFetchSettings
from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    SearchCandidate,
    SearchCapability,
    SearchResult,
    SearchStatus,
)
from app.estimator.searched_reference import (
    _REFERENCE_PAGE_KIND,
    MAX_SNIPPET_TEXT_CHARS,
    MAX_SOURCE_REF_LEN,
    REFERENCE_SOURCE,
    REFERENCE_SOURCE_TYPE,
    SNIPPET_ASSUMPTION,
    searched_reference_per_100g,
)
from app.estimator.user_text_step import UserTextMacroEstimator
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


class RecordingReferenceFetcher:
    """Network-free two-argument reference fetch seam for user_text tests."""

    def __init__(self, pages: dict[str, str]) -> None:
        self._pages = pages
        self.fetched: list[str] = []

    def __call__(self, url: str, settings: ReferenceFetchSettings) -> str:
        self.fetched.append(url)
        return self._pages[url]


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


def test_user_text_exact_reference_skips_zero_calorie_candidate_and_uses_later_page() -> None:
    """user_text cannot scale missing macros from zero kcal, so it keeps scanning."""

    zero = "https://example.com/zero"
    good = "https://example.com/good"
    search = FakeSearchProvider(
        SearchResult(
            status=SearchStatus.SUCCESS,
            candidates=(
                SearchCandidate(url=zero, title="zero calorie wrap"),
                SearchCandidate(url=good, title="buffalo chicken wrap nutrition"),
            ),
        )
    )
    fetcher = RecordingReferenceFetcher({zero: "zero page", good: "good page"})
    provider = FakeProvider(
        responses=[
            {
                "disposition": "resolved",
                "confidence": 0.9,
                "facts": {
                    "basis": "per_100g",
                    "calories": 0.0,
                    "protein_g": 0.0,
                    "carbs_g": 0.0,
                    "fat_g": 0.0,
                },
            },
            _estimate(),
        ]
    )
    estimator = UserTextMacroEstimator(
        provider=provider,
        search_provider=search,
        reference_fetch_settings=ReferenceFetchSettings(),
        reference_fetch_fn=fetcher,
    )
    context = EstimationContext(log_event_id=uuid.uuid4(), user_id=uuid.uuid4(), raw_text="")
    candidate = CandidateDraft(
        name="buffalo chicken lime wrap",
        brand="Sobeys",
        quantity_text="1",
        stated_calories=580.0,
    )

    estimated = estimator.estimate(context, candidate, 580.0, ("protein_g", "carbs_g", "fat_g"))

    assert estimated.source_ref == f"{REFERENCE_SOURCE_TYPE}:{good}"
    assert estimated.values == {
        "protein_g": 29.0,
        "carbs_g": 87.0,
        "fat_g": 14.5,
    }
    assert fetcher.fetched == [zero, good]
    assert context.source_refs == [REFERENCE_SOURCE]


# --- Snippet fallback: bounded, untrusted, fetch-first (FTY-314) ----------------

_SNIPPET_URL = "https://reference.example.com/toppables"
_SNIPPET = "Serving Size Per 60 g. Calories 120. Fat 3 g. Carbs 18 g. Protein 6 g."


def _snippet_candidate(snippet: str = _SNIPPET) -> SearchCandidate:
    return SearchCandidate(url=_SNIPPET_URL, title="Toppables crackers", snippet=snippet)


def _unresolved() -> dict[str, Any]:
    return {"disposition": "unresolved", "confidence": 0.1}


def _search(*candidates: SearchCandidate) -> FakeSearchProvider:
    return FakeSearchProvider(
        SearchResult(status=SearchStatus.SUCCESS, candidates=tuple(candidates))
    )


def test_snippet_fallback_used_when_fetch_fails() -> None:
    search = _search(_snippet_candidate())
    fetcher = RecordingFetcher({})  # fetch returns None: the page was unusable
    provider = FakeProvider(responses=[_estimate()])

    found = searched_reference_per_100g(
        provider=provider,
        search_provider=search,
        fetch=fetcher,
        query="toppables crackers nutrition facts",
        page_kind=_REFERENCE_PAGE_KIND,
        source_type=REFERENCE_SOURCE_TYPE,
    )

    assert found is not None
    # Provenance stays the search-result URL, plus the snippet-derived label.
    assert found.source_ref == f"{REFERENCE_SOURCE_TYPE}:{_SNIPPET_URL}"
    assert found.hash_key == _SNIPPET_URL
    assert found.assumptions == ("source states one wrap serving", SNIPPET_ASSUMPTION)
    assert found.facts.calories == pytest.approx(200.0)
    # The one extraction prompt carried the bounded title+snippet framed as
    # untrusted search-result text, not the (unfetchable) page.
    assert len(provider.prompts) == 1
    prompt = provider.prompts[0]
    assert "search-result title and snippet" in prompt
    assert "Toppables crackers" in prompt
    assert _SNIPPET in prompt
    assert "UNTRUSTED" in prompt


def test_snippet_fallback_used_when_page_extraction_is_unresolved() -> None:
    search = _search(_snippet_candidate())
    fetcher = RecordingFetcher({_SNIPPET_URL: "Please enable JavaScript to continue."})
    provider = FakeProvider(responses=[_unresolved(), _estimate()])

    found = searched_reference_per_100g(
        provider=provider,
        search_provider=search,
        fetch=fetcher,
        query="toppables crackers nutrition facts",
        page_kind=_REFERENCE_PAGE_KIND,
        source_type=REFERENCE_SOURCE_TYPE,
    )

    assert found is not None
    assert SNIPPET_ASSUMPTION in found.assumptions
    # First the fetched shell text, then the snippet fallback.
    assert len(provider.prompts) == 2
    assert "Please enable JavaScript" in provider.prompts[0]
    assert _SNIPPET in provider.prompts[1]


def test_empty_snippet_preserves_fetch_only_behavior() -> None:
    # No snippet → the candidate is exhausted once its fetch fails; the title alone
    # is never an evidence surface, so no extraction call happens at all.
    search = _search(SearchCandidate(url=_SNIPPET_URL, title="Toppables crackers"))
    fetcher = RecordingFetcher({})
    provider = FakeProvider(responses=[_estimate()])

    found = searched_reference_per_100g(
        provider=provider,
        search_provider=search,
        fetch=fetcher,
        query="toppables crackers nutrition facts",
        page_kind=_REFERENCE_PAGE_KIND,
        source_type=REFERENCE_SOURCE_TYPE,
    )

    assert found is None
    assert provider.prompts == []
    assert fetcher.fetched == [_SNIPPET_URL]


def test_successful_page_extraction_never_consults_the_snippet() -> None:
    search = _search(_snippet_candidate())
    fetcher = RecordingFetcher({_SNIPPET_URL: "a real nutrition page"})
    provider = FakeProvider(responses=[_estimate()])

    found = searched_reference_per_100g(
        provider=provider,
        search_provider=search,
        fetch=fetcher,
        query="toppables crackers nutrition facts",
        page_kind=_REFERENCE_PAGE_KIND,
        source_type=REFERENCE_SOURCE_TYPE,
    )

    assert found is not None
    assert SNIPPET_ASSUMPTION not in found.assumptions
    assert len(provider.prompts) == 1
    assert "a real nutrition page" in provider.prompts[0]
    assert _SNIPPET not in provider.prompts[0]


def test_unresolved_snippet_falls_through_to_the_next_candidate() -> None:
    good = "https://reference.example.com/other"
    search = _search(
        _snippet_candidate(),
        SearchCandidate(url=good, title="other crackers"),
    )
    fetcher = RecordingFetcher({good: "a real nutrition page"})
    provider = FakeProvider(responses=[_unresolved(), _estimate()])

    found = searched_reference_per_100g(
        provider=provider,
        search_provider=search,
        fetch=fetcher,
        query="toppables crackers nutrition facts",
        page_kind=_REFERENCE_PAGE_KIND,
        source_type=REFERENCE_SOURCE_TYPE,
    )

    assert found is not None
    assert found.source_ref == f"{REFERENCE_SOURCE_TYPE}:{good}"
    assert SNIPPET_ASSUMPTION not in found.assumptions
    assert fetcher.fetched == [_SNIPPET_URL, good]


def test_snippet_text_is_bounded_before_it_reaches_the_prompt() -> None:
    # Defence in depth: even a hand-built oversized snippet (bypassing the adapter
    # bound) is truncated before the extraction prompt.
    oversized = "x" * (MAX_SNIPPET_TEXT_CHARS * 3)
    search = _search(_snippet_candidate(snippet=oversized))
    fetcher = RecordingFetcher({})
    provider = FakeProvider(responses=[_estimate()])

    searched_reference_per_100g(
        provider=provider,
        search_provider=search,
        fetch=fetcher,
        query="toppables crackers nutrition facts",
        page_kind=_REFERENCE_PAGE_KIND,
        source_type=REFERENCE_SOURCE_TYPE,
    )

    assert len(provider.prompts) == 1
    assert "x" * (MAX_SNIPPET_TEXT_CHARS + 1) not in provider.prompts[0]
