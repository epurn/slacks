"""FTY-435 acceptance tests: search-call hygiene through the real resolution pipeline.

Drive the real parse → food → official/reference cascade with the wrapped search
provider in place (network-free fakes throughout), proving the outbound-call
behaviour the dogfood report asked for:

- a run never re-issues a sanitized query it already asked, even when two items in
  the same event walk the same identity variants — and the second item still
  resolves with byte-identical facts, evidence, and provenance, so a memo/cache hit
  is invisible downstream;
- a ``rate_limited`` reply stops the tier's remaining identity variants and trips
  the cooldown, during which the next tier makes **no** provider call and the run
  falls through to model prior — completing with honest provenance, never a
  user-visible failure;
- with a healthy provider and a cold cache the resolved row, evidence record, and
  provenance are unchanged from the pre-hygiene fixture expectations.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import DerivedItemStatus, EstimationJobStatus, LogEventStatus
from app.estimator.branded_routing import identity_variants
from app.estimator.food_resolvers import FoodResolver
from app.estimator.food_step import FoodResolveStep
from app.estimator.official_step import OfficialSourceResolveStep
from app.estimator.parse import ParseStep
from app.estimator.pipeline import CandidateDraft, Pipeline
from app.estimator.processing import process_estimation
from app.estimator.reference_fetch import ReferenceFetchSettings
from app.estimator.search import (
    OFFICIAL_SOURCE_TYPE,
    HygienicSearchProvider,
    RateLimitCooldown,
    SearchResult,
    SearchResultCache,
    SearchStatus,
)
from app.estimator.searched_reference import (
    MODEL_PRIOR_SOURCE_TYPE,
    REFERENCE_SEARCH_INTENT,
    REFERENCE_SOURCE_TYPE,
)
from app.estimator.self_consistency import SELF_CONSISTENCY_FIRST_WINDOW
from app.llm.providers.fake import FakeProvider
from app.models.food_sources import EvidenceSource
from tests.test_official_source_resolution import (
    _BIG_MAC_URL,
    _PAGE_FACTS,
    FakeFoodSource,
    FakeSearchProvider,
    RecordingFetcher,
    _evidence,
    _fetch_settings,
    _foods,
    _seed_event,
    _success_result,
)

#: The one identity variant a plain ``name + brand`` Big Mac candidate searches.
_OFFICIAL_QUERY = "Big Mac McDonald's"


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


class _FakeClock:
    """A manually advanced monotonic clock for TTL / cooldown determinism."""

    def __init__(self) -> None:
        self.now = 5_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _ScriptedSearchProvider(FakeSearchProvider):
    """A per-query scripted search provider, so each tier gets its own outcome."""

    def __init__(self, results: dict[str, SearchResult]) -> None:
        super().__init__(SearchResult(status=SearchStatus.PARTIAL))
        self._results = results

    def search(self, query: str) -> SearchResult:
        self.queries.append(query)
        return self._results[query]


def _hygienic(
    inner: FakeSearchProvider,
    *,
    clock: _FakeClock,
    cache: SearchResultCache | None = None,
    cooldown: RateLimitCooldown | None = None,
) -> HygienicSearchProvider:
    """Wrap a scripted provider exactly as the production factory does."""

    return HygienicSearchProvider(
        inner,
        scope="searxng",
        cache_ttl_seconds=300.0,
        cooldown_seconds=60.0,
        cache=cache if cache is not None else SearchResultCache(clock=clock),
        cooldown=cooldown if cooldown is not None else RateLimitCooldown(clock=clock),
    )


def _pipeline_with_items(
    session: Session,
    *,
    parsed_items: list[dict[str, object]],
    search_provider: HygienicSearchProvider,
    fetcher: RecordingFetcher,
    estimates: list[dict[str, Any]],
    reference_fetcher: RecordingFetcher | None = None,
    reference_settings: ReferenceFetchSettings | None = None,
) -> Pipeline:
    """The real parse + food + official/reference pipeline for a multi-item event."""

    parse_provider = FakeProvider(
        responses=[{"disposition": "parsed", "confidence": 0.95, "items": parsed_items}]
        * SELF_CONSISTENCY_FIRST_WINDOW
    )
    official_step = OfficialSourceResolveStep(
        provider=FakeProvider(responses=list(estimates)),
        search_provider=search_provider,
        fetch_settings=_fetch_settings(),
        reference_fetch_settings=reference_settings or ReferenceFetchSettings(),
        fetch_fn=fetcher,
        reference_fetch_fn=reference_fetcher or fetcher,
    )
    resolver = FoodResolver(session=session, source=FakeFoodSource({}))
    return Pipeline([ParseStep(parse_provider), FoodResolveStep(resolver), official_step])


def _big_mac(quantity_text: str = "1") -> dict[str, object]:
    return {
        "type": "food",
        "name": "Big Mac",
        "brand": "McDonald's",
        "quantity_text": quantity_text,
        "amount": 1,
    }


def _page_estimate() -> dict[str, Any]:
    return {"disposition": "resolved", "confidence": 0.9, "facts": _PAGE_FACTS}


def _draft(parsed_item: dict[str, object]) -> CandidateDraft:
    """The candidate draft a parsed item becomes, for identity-variant assertions."""

    return CandidateDraft(
        name=str(parsed_item["name"]),
        brand=str(parsed_item["brand"]),
        quantity_text=str(parsed_item["quantity_text"]),
    )


# --- Per-run dedup across the tier walks --------------------------------------


def test_repeated_identity_in_one_run_searches_once_and_both_items_resolve(
    client: TestClient,
    session: Session,
) -> None:
    # FTY-435 acceptance: within one run the same sanitized query reaches the provider
    # at most once. Two components with the same identity walk the same official
    # variant; the second is served from the run memo — and still resolves with the
    # same facts, evidence, and provenance, so the hit is invisible downstream.
    user_id, event_id = _seed_event(client, "hygiene-dedup@example.com", "two Big Macs")
    inner = FakeSearchProvider(_success_result())
    fetcher = RecordingFetcher()
    pipeline = _pipeline_with_items(
        session,
        parsed_items=[_big_mac(), _big_mac()],
        search_provider=_hygienic(inner, clock=_FakeClock()),
        fetcher=fetcher,
        estimates=[_page_estimate(), _page_estimate()],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    # One provider call for the one distinct sanitized query, not one per item.
    assert inner.queries == [_OFFICIAL_QUERY]

    foods = _foods(session, event_id)
    assert len(foods) == 2
    for food in foods:
        assert food.status == DerivedItemStatus.RESOLVED
        assert food.grams == 219.0
        assert food.calories == 547.5
    # Both items fetched and extracted their own evidence from the cached candidate.
    assert fetcher.fetched == [_BIG_MAC_URL, _BIG_MAC_URL]
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).all()
    assert len(evidence) == 2
    for row in evidence:
        assert row.source_type == OFFICIAL_SOURCE_TYPE
        assert row.source_ref == f"official_source:{_BIG_MAC_URL}"
        assert row.calories_per_100g == 250.0
        assert row.assumptions is None


def test_both_tier_walks_issue_each_distinct_query_once(
    client: TestClient,
    session: Session,
) -> None:
    # FTY-435 acceptance, the fan-out shape the dogfood note hit: two components share
    # an identity and each walks *both* web-evidence tiers (the official tier's search
    # finds nothing usable, the reference tier resolves). That is four lookups over two
    # distinct sanitized queries — the provider must see each exactly once.
    user_id, event_id = _seed_event(client, "hygiene-two-tiers@example.com", "two Big Macs")
    reference_query = f"{_OFFICIAL_QUERY} {REFERENCE_SEARCH_INTENT}"
    inner = _ScriptedSearchProvider(
        {
            _OFFICIAL_QUERY: SearchResult(status=SearchStatus.PARTIAL),
            reference_query: _success_result(),
        }
    )
    fetcher = RecordingFetcher()
    hygienic = _hygienic(inner, clock=_FakeClock())
    pipeline = _pipeline_with_items(
        session,
        parsed_items=[_big_mac(), _big_mac()],
        search_provider=hygienic,
        fetcher=fetcher,
        estimates=[_page_estimate(), _page_estimate()],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    assert inner.queries == [_OFFICIAL_QUERY, reference_query]
    assert hygienic.stats.provider_calls == 2
    assert hygienic.stats.memo_hits == 2
    # Both items still resolved from their own reference-page evidence.
    foods = _foods(session, event_id)
    assert len(foods) == 2
    assert all(food.calories == 547.5 for food in foods)
    evidence = session.scalars(
        select(EvidenceSource).where(EvidenceSource.log_event_id == event_id)
    ).all()
    assert [row.source_type for row in evidence] == [REFERENCE_SOURCE_TYPE] * 2


def test_second_run_inside_the_ttl_resolves_from_the_cache_without_searching(
    client: TestClient,
    session: Session,
) -> None:
    # FTY-435 acceptance: across runs inside the TTL the repeated query is served from
    # the shared cache with no provider call, and the entry refreshes after the TTL —
    # with the resolved row and evidence identical either way (an injectable clock, so
    # the expiry is deterministic and needs no wall-clock wait).
    clock = _FakeClock()
    cache = SearchResultCache(clock=clock)
    cooldown = RateLimitCooldown(clock=clock)
    inner = FakeSearchProvider(_success_result())

    def _run(email: str) -> EvidenceSource:
        user_id, event_id = _seed_event(client, email, "a Big Mac")
        pipeline = _pipeline_with_items(
            session,
            parsed_items=[_big_mac()],
            search_provider=_hygienic(inner, clock=clock, cache=cache, cooldown=cooldown),
            fetcher=RecordingFetcher(),
            estimates=[_page_estimate()],
        )
        result = process_estimation(
            session, log_event_id=event_id, user_id=user_id, pipeline=pipeline
        )
        assert result.event_status is LogEventStatus.COMPLETED
        assert _foods(session, event_id)[0].calories == 547.5
        return _evidence(session, event_id)

    first = _run("hygiene-ttl-1@example.com")
    assert inner.queries == [_OFFICIAL_QUERY]

    clock.advance(299.0)
    cached_run = _run("hygiene-ttl-2@example.com")
    # No second search: the answered lookup came from the cache, and the evidence the
    # run recorded is the same source, ref, and facts as the cold-cache run.
    assert inner.queries == [_OFFICIAL_QUERY]
    assert cached_run.source_type == first.source_type
    assert cached_run.source_ref == first.source_ref
    assert cached_run.calories_per_100g == first.calories_per_100g
    assert cached_run.assumptions == first.assumptions

    clock.advance(2.0)  # past the 300 s TTL
    _run("hygiene-ttl-3@example.com")
    assert inner.queries == [_OFFICIAL_QUERY, _OFFICIAL_QUERY]


# --- Healthy-provider parity (cold cache) ------------------------------------


def test_healthy_provider_cold_cache_is_unchanged_by_hygiene(
    client: TestClient,
    session: Session,
) -> None:
    # FTY-435 acceptance: with a healthy provider and a cold cache the outcome is
    # identical to the pre-hygiene fixture — same query, same fetch, same resolved
    # numbers, same evidence row and provenance (cf.
    # test_official_source_resolution.test_branded_food_resolves_from_official_source).
    user_id, event_id = _seed_event(client, "hygiene-parity@example.com", "a Big Mac")
    inner = FakeSearchProvider(_success_result())
    fetcher = RecordingFetcher()
    reference_fetcher = RecordingFetcher()
    pipeline = _pipeline_with_items(
        session,
        parsed_items=[_big_mac()],
        search_provider=_hygienic(inner, clock=_FakeClock()),
        fetcher=fetcher,
        reference_fetcher=reference_fetcher,
        estimates=[_page_estimate()],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    food = _foods(session, event_id)[0]
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.grams == 219.0
    assert food.calories == 547.5
    assert food.protein_g == pytest.approx(21.9)
    assert food.carbs_g == pytest.approx(65.7)
    assert food.fat_g == pytest.approx(19.7)
    evidence = _evidence(session, event_id)
    assert evidence.source_type == OFFICIAL_SOURCE_TYPE
    assert evidence.source_ref == f"official_source:{_BIG_MAC_URL}"
    assert evidence.calories_per_100g == 250.0
    assert evidence.assumptions is None
    assert inner.queries == [_OFFICIAL_QUERY]
    assert fetcher.fetched == [_BIG_MAC_URL]
    assert reference_fetcher.fetched == []


# --- 429 short-circuit + cooldown --------------------------------------------


def test_rate_limited_search_stops_the_walk_and_falls_through_to_model_prior(
    client: TestClient,
    session: Session,
) -> None:
    # FTY-435 acceptance: the first rate-limit reply halts the tier's remaining
    # variants and trips the cooldown, so the reference tier makes no provider call at
    # all. The run still completes: model prior costs the item with honest,
    # content-free provenance naming the rate limit — never a user-visible failure.
    user_id, event_id = _seed_event(client, "hygiene-429@example.com", "a Big Mac")
    inner = FakeSearchProvider(SearchResult(status=SearchStatus.RATE_LIMITED))
    fetcher = RecordingFetcher()
    hygienic = _hygienic(inner, clock=_FakeClock())
    # A product hint gives the candidate several identity variants per tier, so the halt
    # is observable rather than vacuous: without hygiene this walk would issue three
    # official + three reference queries to an instance that already said "429".
    hinted = _big_mac(quantity_text="1 quarter pounder box")
    assert len(identity_variants(_draft(hinted))) > 1
    pipeline = _pipeline_with_items(
        session,
        parsed_items=[hinted],
        search_provider=hygienic,
        fetcher=fetcher,
        estimates=[
            {
                "disposition": "resolved",
                "confidence": 0.7,
                "facts": _PAGE_FACTS,
                "assumptions": ["estimated from model prior"],
            }
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.job_status is EstimationJobStatus.SUCCEEDED
    assert result.event_status is LogEventStatus.COMPLETED
    # Exactly one search egressed: the official tier's first variant. The rest of that
    # tier's variants and the whole reference tier were served by the cooldown.
    assert len(inner.queries) == 1
    assert hygienic.stats.provider_calls == 1
    assert hygienic.stats.cooldown_trips == 1
    # Exactly one call-free lookup: the reference tier's *first* variant. Both tiers
    # stopped their walk on the rate limit — three variants each would otherwise have
    # produced five more lookups.
    assert hygienic.stats.cooldown_skips == 1
    # No page was fetched: a rate-limited lookup yields no candidate to fetch.
    assert fetcher.fetched == []

    food = _foods(session, event_id)[0]
    assert food.status == DerivedItemStatus.RESOLVED
    assert food.calories == 547.5
    evidence = _evidence(session, event_id)
    assert evidence.source_type == MODEL_PRIOR_SOURCE_TYPE
    assert evidence.assumptions is not None
    reasons = " | ".join(evidence.assumptions)
    assert f"{OFFICIAL_SOURCE_TYPE} search rate limited" in reasons
    assert f"{REFERENCE_SOURCE_TYPE} search rate limited" in reasons


def test_cooldown_from_an_earlier_run_skips_search_entirely(
    client: TestClient,
    session: Session,
) -> None:
    # The cooldown is process-shared, so a run that starts while it is active makes no
    # provider call at all and still completes through model prior.
    clock = _FakeClock()
    cooldown = RateLimitCooldown(clock=clock)
    cooldown.trip("searxng", cooldown_seconds=60.0)
    user_id, event_id = _seed_event(client, "hygiene-cooldown@example.com", "a Big Mac")
    inner = FakeSearchProvider(_success_result())
    fetcher = RecordingFetcher()
    hygienic = _hygienic(inner, clock=clock, cooldown=cooldown)
    pipeline = _pipeline_with_items(
        session,
        parsed_items=[_big_mac()],
        search_provider=hygienic,
        fetcher=fetcher,
        estimates=[
            {
                "disposition": "resolved",
                "confidence": 0.7,
                "facts": _PAGE_FACTS,
                "assumptions": ["estimated from model prior"],
            }
        ],
    )

    result = process_estimation(session, log_event_id=event_id, user_id=user_id, pipeline=pipeline)

    assert result.event_status is LogEventStatus.COMPLETED
    assert inner.queries == []
    assert hygienic.stats.provider_calls == 0
    assert fetcher.fetched == []
    assert _evidence(session, event_id).source_type == MODEL_PRIOR_SOURCE_TYPE
    assert _foods(session, event_id)[0].status == DerivedItemStatus.RESOLVED
