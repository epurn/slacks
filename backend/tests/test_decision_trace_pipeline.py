"""Integration tests for the sanitized estimator decision trace (FTY-255).

Drive :func:`app.estimator.processing.process_estimation` with the real
:class:`ParseStep` + :class:`FoodResolveStep` + :class:`OfficialSourceResolveStep`
(all network seams faked) and prove that the persisted run ``trace`` alone —
without querying ``products`` or any other table — explains the two audit
failures that motivated the story:

- **Compliments-style needs-clarification** (2026-07-05 audit): a branded
  candidate is present, the USDA FDC row was considered and rejected for brand
  mismatch, the candidate was deferred to web evidence, both search tiers were
  unavailable, and the terminal clarify reason is recorded.
- **Toppables/PC-hummus-style model-prior completion** (2026-07-09 audit): a
  search variant missed while another hit, an exact product URL's fetch returned
  403 or empty shell text, the snippet fallback was attempted and rejected, the
  FDC pickles-vs-hummus row was rejected, and the model-prior fallback (with the
  configured provider/model identity) is recorded.

Both scenarios also prove the hard privacy rule: no raw event text, no page
text, and no secret-looking search-result query parameters survive into
``estimation_runs.trace``.
"""

from __future__ import annotations

import uuid
from collections import deque
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import EstimationJobStatus, LogEventStatus
from app.estimator.fdc import ProductFacts
from app.estimator.food_resolvers import FoodResolver
from app.estimator.food_serving import NutritionFacts
from app.estimator.food_step import FoodResolveStep
from app.estimator.hardened_fetch import FetchResponseError
from app.estimator.official_fetch import OfficialFetchSettings
from app.estimator.official_step import OfficialSourceResolveStep
from app.estimator.parse import ParseStep
from app.estimator.pipeline import CandidateDraft, EstimationContext, Pipeline
from app.estimator.processing import process_estimation
from app.estimator.reference_fetch import ReferenceFetchSettings
from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    SearchCandidate,
    SearchCapability,
    SearchResult,
    SearchStatus,
)
from app.estimator.searched_reference import MODEL_PRIOR_SOURCE_TYPE
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.providers.fake import FakeProvider
from app.models.estimation import EstimationRun
from app.models.food_sources import EvidenceSource

_HIT_URL_403 = "https://shop.example.com/products/pc-hummus?api_key=TOPSECRETQUERY42&s=1"
_HIT_URL_EMPTY = "https://shop.example.com/products/pc-hummus-tub"

#: Sentinel embedded in raw text / snippets, asserted absent from the trace.
_RAW_TEXT = "my secret snack sk-secretlooking1234 \x1f two tbsp of PC hummus"
_SNIPPET_SENTINEL = "SNIPPET-BODY-SENTINEL"

_MODEL_PRIOR_FACTS = {
    "basis": "per_100g",
    "product_name": "hummus",
    "calories": 170.0,
    "protein_g": 5.0,
    "carbs_g": 12.0,
    "fat_g": 10.0,
    "serving_size_amount": 30.0,
    "serving_size_unit": "g",
}


class FakeFoodSource:
    """A scripted, network-free generic-food source (USDA stand-in)."""

    def __init__(self, facts: dict[str, ProductFacts] | None = None) -> None:
        self._facts = facts or {}

    @property
    def enabled(self) -> bool:
        return True

    def lookup(self, query: str) -> ProductFacts | None:
        return self._facts.get(query.strip().lower())


class QueueSearchProvider:
    """A scripted search adapter returning one queued result per lookup.

    An exhausted queue keeps answering ``partial`` (no candidates), so variant
    counts never have to match the script length exactly.
    """

    def __init__(
        self,
        results: list[SearchResult] | None = None,
        *,
        enabled: bool = True,
        available: bool = True,
    ) -> None:
        self._results = deque(results or [])
        self._enabled = enabled
        self._available = available
        self.queries: list[str] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def available(self) -> bool:
        return self._available

    @property
    def capability(self) -> SearchCapability:
        return SearchCapability(
            id="official_source",
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=("named_product", "restaurant_item"),
            enabled=self._enabled,
            available=self._available,
        )

    def search(self, query: str) -> SearchResult:
        self.queries.append(query)
        if self._results:
            return self._results.popleft()
        return SearchResult(status=SearchStatus.PARTIAL)


class ScriptedFetcher:
    """A network-free fetcher mapping each URL to a page text or a raised error."""

    def __init__(self, behaviors: dict[str, str | Exception]) -> None:
        self._behaviors = behaviors
        self.fetched: list[str] = []

    def __call__(self, url: str, settings: object) -> str:
        self.fetched.append(url)
        behavior = self._behaviors.get(url, "")
        if isinstance(behavior, Exception):
            raise behavior
        return behavior


def _fdc_row(*, description: str, source_ref: str, query_key: str) -> ProductFacts:
    return ProductFacts(
        source="usda_fdc",
        source_ref=source_ref,
        query_key=query_key,
        description=description,
        facts=NutritionFacts(calories=91.0, protein_g=0.6, carbs_g=21.1, fat_g=0.2),
        default_serving_g=100.0,
        content_hash="deadbeef",
    )


def _pipeline(
    session: Session,
    *,
    parsed_item: dict[str, object],
    food_source: FakeFoodSource,
    search_provider: QueueSearchProvider,
    fetcher: ScriptedFetcher,
    estimates: list[dict[str, Any]],
    parse_model: str = "fake-audit-model",
) -> Pipeline:
    parse_provider = FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": [parsed_item]}]
        * SELF_CONSISTENCY_FIRST_WINDOW,
        model=parse_model,
    )
    official_step = OfficialSourceResolveStep(
        provider=FakeProvider(responses=list(estimates)),
        search_provider=search_provider,
        fetch_settings=OfficialFetchSettings(allowed_hosts=frozenset({"shop.example.com"})),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=fetcher,
        reference_fetch_fn=fetcher,
    )
    resolver = FoodResolver(session=session, source=food_source)
    return Pipeline([ParseStep(parse_provider), FoodResolveStep(resolver), official_step])


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


def _run(session: Session, event_id: uuid.UUID) -> EstimationRun:
    return session.scalars(
        select(EstimationRun).where(EstimationRun.log_event_id == event_id)
    ).one()


def _decisions(run: EstimationRun) -> list[dict[str, Any]]:
    return [entry for entry in run.trace if "decision" in entry]


def _find(entries: list[dict[str, Any]], **fields: object) -> list[dict[str, Any]]:
    return [
        entry for entry in entries if all(entry.get(key) == value for key, value in fields.items())
    ]


def test_compliments_style_clarification_trace_explains_terminal_state(
    client: TestClient, session: Session
) -> None:
    """A needs-clarification run's trace explains the route without a products query."""

    user_id, event_id = _seed_event(client, "trace-compliments@example.com", _RAW_TEXT)
    pipeline = _pipeline(
        session,
        parsed_item={
            "type": "food",
            "name": "chicken strips",
            "brand": "Compliments",
            "quantity_text": "",
        },
        # The FTY-253 audit shape: FDC answers the generic name with a *different*
        # product identity, so the row must be rejected, not trusted.
        food_source=FakeFoodSource(
            {
                "chicken strips": _fdc_row(
                    description="DENNY'S, chicken strips",
                    source_ref="usda_fdc:167935",
                    query_key="chicken strips",
                )
            }
        ),
        # Search is entirely off, so both web tiers are unavailable and the model
        # prior is the only remaining tier; it cannot estimate → clarification.
        search_provider=QueueSearchProvider(enabled=False),
        fetcher=ScriptedFetcher({}),
        estimates=[{"disposition": "unresolved", "confidence": 0.0}],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.NEEDS_CLARIFICATION
    assert result.event_status is LogEventStatus.NEEDS_CLARIFICATION

    run = _run(session, event_id)
    entries = _decisions(run)

    # Branded candidate present, with its structural shape (no copied text).
    candidate = _find(entries, decision="candidate", candidate_index=0)
    assert candidate and candidate[0]["has_brand"] is True
    assert candidate[0]["amount_kind"] == "missing"

    # FDC saw the candidate and rejected the concrete row for brand mismatch —
    # the ref and global description are in the trace, so no products query is
    # needed to know which row was turned away.
    rejected = _find(entries, decision="source", tier="usda_fdc", outcome="rejected_brand_mismatch")
    assert rejected and rejected[0]["source_ref"] == "usda_fdc:167935"
    assert "DENNY" in rejected[0]["source_desc"]

    # Deferred to web evidence; both search tiers explicitly unavailable.
    assert _find(entries, decision="outcome", outcome="deferred_to_web_evidence")
    assert _find(entries, tier="official_source", outcome="search_disabled")
    assert _find(entries, tier="reference_source", outcome="search_disabled")

    # The model prior could not estimate, and the terminal clarify is recorded.
    assert _find(entries, tier="model_prior", outcome="model_prior_unavailable")
    assert _find(entries, decision="outcome", outcome="clarified_unknown_food")

    # Hard rule: no raw event text or secret-looking content in the trace.
    serialized = str(run.trace)
    assert _RAW_TEXT not in serialized
    assert "secret snack" not in serialized
    assert "sk-secretlooking1234" not in serialized


def test_toppables_style_model_prior_trace_explains_web_evidence_misses(
    client: TestClient, session: Session
) -> None:
    """A completed model-prior run's trace explains every web-evidence miss."""

    user_id, event_id = _seed_event(client, "trace-toppables@example.com", _RAW_TEXT)
    search = QueueSearchProvider(
        [
            # Official tier, variant 0: the search misses outright.
            SearchResult(status=SearchStatus.PARTIAL),
            # Variant 1: two exact product URLs surface. The first fetch is
            # rejected (403) and has no snippet; the second returns empty shell
            # text and its snippet extraction is low-confidence.
            SearchResult(
                status=SearchStatus.SUCCESS,
                candidates=(
                    SearchCandidate(url=_HIT_URL_403, title="PC Hummus | Shop"),
                    SearchCandidate(
                        url=_HIT_URL_EMPTY,
                        title="PC Hummus Tub",
                        snippet=f"{_SNIPPET_SENTINEL} creamy hummus",
                    ),
                ),
            ),
            # Remaining official + all reference variants: the queue is exhausted
            # and keeps answering partial.
        ]
    )
    pipeline = _pipeline(
        session,
        parsed_item={
            "type": "food",
            "name": "hummus",
            "brand": "PC",
            "quantity_text": "2 tbsp",
            "unit": "tbsp",
            "amount": 2,
        },
        # The 2026-07-09 audit shape: FDC answers "hummus" with a pickles row.
        food_source=FakeFoodSource(
            {
                "hummus": _fdc_row(
                    description="Pickles, cucumber, dill",
                    source_ref="usda_fdc:168558",
                    query_key="hummus",
                )
            }
        ),
        search_provider=search,
        fetcher=ScriptedFetcher(
            {
                _HIT_URL_403: FetchResponseError("provider returned an error", status_code=403),
                _HIT_URL_EMPTY: "   ",
            }
        ),
        estimates=[
            # Empty-shell page text extracts nothing.
            {"disposition": "unresolved", "confidence": 0.0},
            # Snippet fallback answers, but below the confidence floor.
            {"disposition": "resolved", "confidence": 0.2, "facts": _MODEL_PRIOR_FACTS},
            # Model prior succeeds with plausible per-100g facts.
            {"disposition": "resolved", "confidence": 0.9, "facts": _MODEL_PRIOR_FACTS},
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED

    run = _run(session, event_id)
    entries = _decisions(run)

    # FDC pickles-vs-hummus rejection, with the concrete row.
    rejected = _find(entries, decision="source", tier="usda_fdc", outcome="rejected_brand_mismatch")
    assert rejected and rejected[0]["source_ref"] == "usda_fdc:168558"
    assert "Pickles" in rejected[0]["source_desc"]

    # Search variant miss vs hit, with statuses and candidate counts.
    misses = _find(entries, decision="search", tier="official_source", query_variant=0)
    assert misses and misses[0]["search_status"] == "partial"
    assert misses[0]["result_count"] == 0
    hit = _find(entries, decision="search", tier="official_source", query_variant=1)
    assert hit and hit[0]["search_status"] == "success"
    assert hit[0]["result_count"] == 2

    # The exact product URL whose fetch was rejected (403) — query string gone.
    fetch_403 = _find(entries, decision="fetch", outcome="fetch_403")
    assert fetch_403
    assert (
        fetch_403[0]["source_ref"] == "official_source:https://shop.example.com/products/pc-hummus"
    )
    # Its candidate had no snippet, so the fallback surface was unavailable.
    assert _find(entries, decision="extract", surface="snippet", outcome="snippet_unavailable")

    # The second URL fetched empty shell text; its page extraction resolved
    # nothing and the snippet fallback was attempted but rejected.
    assert _find(entries, decision="fetch", outcome="fetch_empty_text")
    assert _find(entries, decision="extract", surface="page", outcome="extract_unresolved")
    assert _find(entries, decision="extract", surface="snippet", outcome="extract_low_confidence")

    # Model prior was used, and the run records the configured identity.
    assert _find(entries, decision="source", tier="model_prior", outcome="accepted")
    assert run.provider == "fake"
    assert run.model == "fake-audit-model"

    # The resolved item is honestly a model-prior estimate with tier reasons.
    assert run.assumptions and any("model prior" in a for a in run.assumptions)
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).one()
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE

    # Hard rule: no raw text, page/snippet bodies, or secret query params.
    serialized = str(run.trace)
    assert _RAW_TEXT not in serialized
    assert _SNIPPET_SENTINEL not in serialized
    assert "TOPSECRETQUERY42" not in serialized
    assert "sk-secretlooking1234" not in serialized


def test_accepted_snippet_and_count_serving_scaling_are_traced(
    client: TestClient, session: Session
) -> None:
    """The remaining 2026-07-09 audit lines: snippet accepted, count serving scaled."""

    user_id, event_id = _seed_event(client, "trace-crackers@example.com", _RAW_TEXT)
    url = "https://shop.example.com/products/pc-toppables"
    search = QueueSearchProvider(
        [
            SearchResult(
                status=SearchStatus.SUCCESS,
                candidates=(
                    SearchCandidate(
                        url=url,
                        title="PC Toppables Crackers",
                        snippet=f"{_SNIPPET_SENTINEL} 90 calories per 5 crackers",
                    ),
                ),
            ),
        ]
    )
    pipeline = _pipeline(
        session,
        parsed_item={
            "type": "food",
            "name": "toppables crackers",
            "brand": "PC",
            "quantity_text": "4 crackers",
            "unit": "crackers",
            "amount": 4,
        },
        food_source=FakeFoodSource({}),  # USDA miss
        search_provider=search,
        # The exact product page is fetch-blocked, so the only usable evidence
        # surface is the bounded search-result snippet (FTY-314).
        fetcher=ScriptedFetcher(
            {url: FetchResponseError("provider returned an error", status_code=500)}
        ),
        estimates=[
            # Snippet transcription states count-serving facts: 90 kcal / 5 crackers.
            {
                "disposition": "resolved",
                "confidence": 0.9,
                "facts": {
                    "basis": "per_serving",
                    "product_name": "PC Toppables crackers",
                    "calories": 90.0,
                    "protein_g": 2.0,
                    "carbs_g": 12.0,
                    "fat_g": 3.5,
                    "serving_count": {"amount": 5.0, "unit": "crackers"},
                },
            },
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED

    run = _run(session, event_id)
    entries = _decisions(run)

    # The page fetch failure, the accepted snippet, and the count-serving scale
    # are each visible with the (query-stripped) product URL.
    ref = f"official_source:{url}"
    assert _find(entries, decision="fetch", outcome="fetch_500", source_ref=ref)
    accepted = _find(entries, decision="extract", surface="snippet", outcome="accepted_snippet")
    assert accepted and accepted[0]["source_ref"] == ref
    assert _find(entries, decision="serving", outcome="count_serving_scaled", source_ref=ref)

    # 4 of "90 kcal per 5 crackers" → 72 kcal, and the snippet body is not stored.
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).one()
    assert evidence.source_ref == f"official_source:{url}"
    serialized = str(run.trace)
    assert _SNIPPET_SENTINEL not in serialized
    assert _RAW_TEXT not in serialized


def test_duplicate_drafts_attribute_official_decisions_to_their_own_index() -> None:
    """Each of two value-equal drafts gets its own downstream ``candidate_index``.

    Drafts are frozen value objects, so two identical parsed candidates compare
    equal and an index-by-equality lookup would attribute the second candidate's
    official/reference/model-prior decisions to the first. The step must key
    attribution on the draft object's own position in the parse list.
    """

    context = EstimationContext(
        log_event_id=uuid.uuid4(), user_id=uuid.uuid4(), raw_text="PC hummus, twice"
    )
    first = CandidateDraft(
        name="hummus", quantity_text="2 tbsp", unit="tbsp", amount=2.0, brand="PC"
    )
    duplicate = CandidateDraft(
        name="hummus", quantity_text="2 tbsp", unit="tbsp", amount=2.0, brand="PC"
    )
    assert first == duplicate  # value objects: equality cannot tell them apart
    context.food_candidates.extend([first, duplicate])
    context.pending_official_candidates.extend([first, duplicate])

    step = OfficialSourceResolveStep(
        provider=FakeProvider(
            responses=[{"disposition": "resolved", "confidence": 0.9, "facts": _MODEL_PRIOR_FACTS}]
            * 2
        ),
        search_provider=QueueSearchProvider(enabled=False),
        fetch_settings=OfficialFetchSettings(allowed_hosts=frozenset({"shop.example.com"})),
        reference_fetch_settings=ReferenceFetchSettings(),
        fetch_fn=ScriptedFetcher({}),
        reference_fetch_fn=ScriptedFetcher({}),
    )
    step.run(context)

    assert len(context.resolved_food_items) == 2
    entries = [entry for entry in context.trace if "decision" in entry]
    for index in (0, 1):
        official = _find(entries, tier="official_source", candidate_index=index)
        assert official and official[0]["outcome"] == "search_disabled"
        reference = _find(entries, tier="reference_source", candidate_index=index)
        assert reference and reference[0]["outcome"] == "search_disabled"
        assert _find(entries, tier="model_prior", outcome="accepted", candidate_index=index)
