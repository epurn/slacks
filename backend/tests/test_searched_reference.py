"""Focused tests for the shared searched-reference → per-100g primitive (FTY-283)."""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from app.estimator.hardened_fetch import FetchResponseError
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
from app.estimator.user_text_macro_estimator import UserTextMacroEstimator
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
    # The transcriber's stated assumptions are provider output from a prompt that
    # carried raw page text; the accepted-page carrier never keeps them.
    assert found.assumptions == ()
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
    # Provenance stays the search-result URL. The assumptions carry ONLY the fixed
    # snippet-derived label: the provider-stated assumptions are dropped for a
    # snippet extraction, so provider output echoing raw snippet text can never
    # ride into evidence/run assumptions.
    assert found.source_ref == f"{REFERENCE_SOURCE_TYPE}:{_SNIPPET_URL}"
    assert found.hash_key == _SNIPPET_URL
    assert found.assumptions == (SNIPPET_ASSUMPTION,)
    assert found.facts.calories == pytest.approx(200.0)
    # The one extraction prompt carried the bounded title+snippet framed as
    # untrusted search-result text, not the (unfetchable) page.
    assert len(provider.prompts) == 1
    prompt = provider.prompts[0]
    assert "search-result title and snippet" in prompt
    assert "Toppables crackers" in prompt
    assert _SNIPPET in prompt
    assert "UNTRUSTED" in prompt


def test_snippet_extraction_drops_provider_stated_assumptions() -> None:
    # Fail-closed retention (FTY-314): the extraction provider controls the
    # ``assumptions`` it returns and could echo raw snippet text into them. A
    # snippet-derived result persists only the fixed content-free label.
    search = _search(_snippet_candidate())
    fetcher = RecordingFetcher({})
    echoing = _estimate()
    echoing["assumptions"] = [f"transcribed from snippet: {_SNIPPET}"]
    provider = FakeProvider(responses=[echoing])

    found = searched_reference_per_100g(
        provider=provider,
        search_provider=search,
        fetch=fetcher,
        query="toppables crackers nutrition facts",
        page_kind=_REFERENCE_PAGE_KIND,
        source_type=REFERENCE_SOURCE_TYPE,
    )

    assert found is not None
    assert found.assumptions == (SNIPPET_ASSUMPTION,)


def test_page_extraction_drops_provider_stated_assumptions() -> None:
    # Fail-closed retention (FTY-326): the page transcriber saw the raw fetched
    # page text in its prompt, so the ``assumptions`` it returns are
    # provider-controlled and could echo that text. An accepted fetched-page
    # result carries no provider-stated assumption strings at all.
    page_sentinel = "RAW-PAGE-ECHO sk-pageassumption123"
    search = _search(_snippet_candidate())
    fetcher = RecordingFetcher({_SNIPPET_URL: f"nutrition facts page {page_sentinel}"})
    echoing = _estimate()
    echoing["assumptions"] = [f"transcribed from page: {page_sentinel}"]
    provider = FakeProvider(responses=[echoing])

    found = searched_reference_per_100g(
        provider=provider,
        search_provider=search,
        fetch=fetcher,
        query="toppables crackers nutrition facts",
        page_kind=_REFERENCE_PAGE_KIND,
        source_type=REFERENCE_SOURCE_TYPE,
    )

    assert found is not None
    assert found.assumptions == ()
    assert page_sentinel not in repr(found)


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

    # The snippet reached the one extraction prompt, but truncated: the composed
    # title+snippet text never exceeds the bound.
    assert len(provider.prompts) == 1
    assert "xxx" in provider.prompts[0]
    assert "x" * (MAX_SNIPPET_TEXT_CHARS + 1) not in provider.prompts[0]


# --- Snippet fallback in the user_text missing-macro path (FTY-314) ---------------


class _FailingReferenceFetcher:
    """Reference fetch seam whose every fetch fails like a 403 page."""

    def __init__(self) -> None:
        self.fetched: list[str] = []

    def __call__(self, url: str, settings: ReferenceFetchSettings) -> str:
        self.fetched.append(url)
        raise FetchResponseError("fetch returned HTTP 403", status_code=403)


def _snippet_extraction(product_name: str | None) -> dict[str, Any]:
    return {
        "disposition": "resolved",
        "confidence": 0.9,
        "facts": {
            "basis": "per_100g",
            "product_name": product_name,
            "calories": 200.0,
            "protein_g": 10.0,
            "carbs_g": 30.0,
            "fat_g": 5.0,
        },
    }


def _macro_context_and_candidate() -> tuple[EstimationContext, CandidateDraft]:
    context = EstimationContext(log_event_id=uuid.uuid4(), user_id=uuid.uuid4(), raw_text="")
    candidate = CandidateDraft(
        name="toppables crackers", quantity_text="a few", stated_calories=360.0
    )
    return context, candidate


def test_user_text_snippet_fill_carries_label_when_product_is_compatible() -> None:
    # The macro fill may use a snippet-derived reference only when its transcribed
    # product identity names a comparable of the item; the persisted assumptions
    # then carry the content-free snippet label alongside the scaling reason.
    search = _search(_snippet_candidate())
    fetcher = _FailingReferenceFetcher()
    provider = FakeProvider(responses=[_snippet_extraction("Toppables crackers")])
    estimator = UserTextMacroEstimator(
        provider=provider,
        search_provider=search,
        reference_fetch_settings=ReferenceFetchSettings(),
        reference_fetch_fn=fetcher,
    )
    context, candidate = _macro_context_and_candidate()

    estimated = estimator.estimate(context, candidate, 360.0, ("protein_g", "carbs_g", "fat_g"))

    assert estimated.source_ref == f"{REFERENCE_SOURCE_TYPE}:{_SNIPPET_URL}"
    assert estimated.values == {"protein_g": 18.0, "carbs_g": 54.0, "fat_g": 9.0}
    assert SNIPPET_ASSUMPTION in estimated.assumptions
    assert fetcher.fetched == [_SNIPPET_URL]


@pytest.mark.parametrize("product_name", ["chocolate fudge cake", None])
def test_user_text_snippet_fill_rejects_incompatible_or_unnamed_product(
    product_name: str | None,
) -> None:
    # Fail closed: this single-source path commits the first accepted result, so a
    # snippet-derived extraction naming a different product — or none at all — never
    # fills missing macros. The estimator falls through, and with the comparable and
    # model-prior tiers yielding nothing the macros stay honestly unknown.
    search = _search(_snippet_candidate())
    fetcher = _FailingReferenceFetcher()
    provider = FakeProvider(
        responses=[
            _snippet_extraction(product_name),
            # Model-prior cold passes: all unresolved → no agreement, no fill.
            {"disposition": "unresolved", "confidence": 0.1},
            {"disposition": "unresolved", "confidence": 0.1},
            {"disposition": "unresolved", "confidence": 0.1},
        ]
    )
    estimator = UserTextMacroEstimator(
        provider=provider,
        search_provider=search,
        reference_fetch_settings=ReferenceFetchSettings(),
        reference_fetch_fn=fetcher,
    )
    context, candidate = _macro_context_and_candidate()

    estimated = estimator.estimate(context, candidate, 360.0, ("protein_g", "carbs_g", "fat_g"))

    assert estimated.values == {}
    assert estimated.source_ref is None
    assert SNIPPET_ASSUMPTION not in estimated.assumptions
