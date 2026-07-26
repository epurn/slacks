"""Unit tests for search-call hygiene: dedup, short-TTL cache, 429 cooldown (FTY-435).

Network-free throughout: a call-counting stub :class:`SearchProvider` plus an
injectable clock, so dedup, TTL refresh, and cooldown expiry are deterministic with
no wall-clock wait. Also pins the privacy rules — cache keys are sanitized queries
only, entries are bounded by TTL and count, and no query text reaches the logs.
"""

from __future__ import annotations

import logging

import pytest

from app.estimator.search import (
    DEFAULT_SEARCH_CACHE_TTL_SECONDS,
    DEFAULT_SEARCH_RATE_LIMIT_COOLDOWN_SECONDS,
    HygienicSearchProvider,
    RateLimitCooldown,
    SearchCandidate,
    SearchCapability,
    SearchResult,
    SearchResultCache,
    SearchSettings,
    SearchStatus,
    build_search_provider,
    load_search_settings,
    shared_rate_limit_cooldown,
    shared_search_cache,
)
from app.estimator.search_providers import SearXNGSearchProvider

_QUERY = "Toppables crackers Compliments"
_OTHER_QUERY = "PC dill pickle hummus"

_CANDIDATE = SearchCandidate(
    url="https://reference.example.com/toppables",
    title="Toppables crackers",
    snippet="Serving Size Per 5 crackers (19 g). Calories 90.",
)


class _FakeClock:
    """A manually advanced monotonic clock."""

    def __init__(self) -> None:
        self.now = 1_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class CountingSearchProvider:
    """A stub provider that counts calls and replays scripted results per query."""

    def __init__(
        self,
        result: SearchResult | None = None,
        *,
        per_query: dict[str, SearchResult] | None = None,
    ) -> None:
        self._result = result or SearchResult(status=SearchStatus.SUCCESS, candidates=(_CANDIDATE,))
        self._per_query = per_query or {}
        self.queries: list[str] = []

    @property
    def calls(self) -> int:
        return len(self.queries)

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
            source_type="official_source",
            kinds=("named_product",),
            enabled=True,
            available=True,
        )

    def search(self, query: str) -> SearchResult:
        self.queries.append(query)
        return self._per_query.get(query, self._result)


def _wrap(
    inner: CountingSearchProvider,
    *,
    clock: _FakeClock,
    cache: SearchResultCache | None = None,
    cooldown: RateLimitCooldown | None = None,
    cache_ttl_seconds: float = 300.0,
    cooldown_seconds: float = 60.0,
) -> HygienicSearchProvider:
    return HygienicSearchProvider(
        inner,
        scope="searxng",
        cache_ttl_seconds=cache_ttl_seconds,
        cooldown_seconds=cooldown_seconds,
        cache=cache if cache is not None else SearchResultCache(clock=clock),
        cooldown=cooldown if cooldown is not None else RateLimitCooldown(clock=clock),
    )


# --- Per-run dedup (memo) -----------------------------------------------------


def test_repeated_query_in_one_run_hits_the_provider_once() -> None:
    clock = _FakeClock()
    inner = CountingSearchProvider()
    provider = _wrap(inner, clock=clock)

    first = provider.search(_QUERY)
    second = provider.search(_QUERY)
    third = provider.search(_QUERY)

    assert inner.calls == 1
    # Indistinguishable downstream: the identical DTO, not a rebuilt lookalike.
    assert second is first
    assert third is first
    assert provider.stats.provider_calls == 1
    assert provider.stats.memo_hits == 2


def test_memo_keys_on_the_sanitized_query() -> None:
    # Two spellings that sanitize to the same egressing string are one call, and the
    # provider still receives the caller's original (its own chokepoint sanitizes).
    clock = _FakeClock()
    inner = CountingSearchProvider()
    provider = _wrap(inner, clock=clock)

    provider.search(_QUERY)
    provider.search("  Toppables\tcrackers   Compliments\n")

    assert inner.queries == [_QUERY]
    assert provider.stats.memo_hits == 1


def test_distinct_queries_each_reach_the_provider() -> None:
    clock = _FakeClock()
    inner = CountingSearchProvider()
    provider = _wrap(inner, clock=clock)

    provider.search(_QUERY)
    provider.search(_OTHER_QUERY)

    assert inner.queries == [_QUERY, _OTHER_QUERY]
    assert provider.stats.memo_hits == 0


def test_failed_lookup_is_memoized_for_the_rest_of_the_run() -> None:
    # A run must never re-issue a query it already asked, whatever the answer.
    clock = _FakeClock()
    inner = CountingSearchProvider(SearchResult(status=SearchStatus.FAILED))
    provider = _wrap(inner, clock=clock)

    assert provider.search(_QUERY).status is SearchStatus.FAILED
    assert provider.search(_QUERY).status is SearchStatus.FAILED
    assert inner.calls == 1


def test_empty_sanitized_query_is_delegated_and_never_cached() -> None:
    clock = _FakeClock()
    cache = SearchResultCache(clock=clock)
    inner = CountingSearchProvider(SearchResult(status=SearchStatus.PARTIAL))
    provider = _wrap(inner, clock=clock, cache=cache)

    result = provider.search("   ")

    assert result.status is SearchStatus.PARTIAL
    assert cache.keys() == ()


# --- Cross-run short-TTL cache ------------------------------------------------


def test_second_run_inside_the_ttl_is_served_from_cache() -> None:
    clock = _FakeClock()
    cache = SearchResultCache(clock=clock)
    inner = CountingSearchProvider()

    first_run = _wrap(inner, clock=clock, cache=cache, cache_ttl_seconds=300.0)
    expected = first_run.search(_QUERY)

    clock.advance(299.0)
    second_run = _wrap(inner, clock=clock, cache=cache, cache_ttl_seconds=300.0)
    served = second_run.search(_QUERY)

    assert inner.calls == 1
    assert served is expected
    assert second_run.stats.cache_hits == 1
    assert second_run.stats.provider_calls == 0


def test_cache_entry_refreshes_after_the_ttl_expires() -> None:
    clock = _FakeClock()
    cache = SearchResultCache(clock=clock)
    inner = CountingSearchProvider()

    _wrap(inner, clock=clock, cache=cache, cache_ttl_seconds=300.0).search(_QUERY)

    clock.advance(301.0)
    later_run = _wrap(inner, clock=clock, cache=cache, cache_ttl_seconds=300.0)
    later_run.search(_QUERY)

    assert inner.calls == 2
    assert later_run.stats.provider_calls == 1
    assert later_run.stats.cache_hits == 0


@pytest.mark.parametrize("status", [SearchStatus.SUCCESS, SearchStatus.PARTIAL])
def test_answered_statuses_are_published_to_the_shared_cache(status: SearchStatus) -> None:
    clock = _FakeClock()
    cache = SearchResultCache(clock=clock)
    candidates = (_CANDIDATE,) if status is SearchStatus.SUCCESS else ()
    inner = CountingSearchProvider(SearchResult(status=status, candidates=candidates))

    _wrap(inner, clock=clock, cache=cache).search(_QUERY)
    _wrap(inner, clock=clock, cache=cache).search(_QUERY)

    assert inner.calls == 1


@pytest.mark.parametrize(
    "status", [SearchStatus.FAILED, SearchStatus.RATE_LIMITED, SearchStatus.UNAVAILABLE]
)
def test_unanswered_statuses_are_never_cached_across_runs(status: SearchStatus) -> None:
    # A transport blip or a throttle window must not suppress search for a later run.
    clock = _FakeClock()
    cache = SearchResultCache(clock=clock)
    inner = CountingSearchProvider(SearchResult(status=status))

    _wrap(inner, clock=clock, cache=cache, cooldown_seconds=0.0).search(_QUERY)
    assert cache.keys() == ()

    _wrap(inner, clock=clock, cache=cache, cooldown_seconds=0.0).search(_QUERY)
    assert inner.calls == 2


def test_zero_ttl_disables_the_shared_cache_but_keeps_the_run_memo() -> None:
    clock = _FakeClock()
    cache = SearchResultCache(clock=clock)
    inner = CountingSearchProvider()

    run = _wrap(inner, clock=clock, cache=cache, cache_ttl_seconds=0.0)
    run.search(_QUERY)
    run.search(_QUERY)
    assert inner.calls == 1
    assert cache.keys() == ()

    _wrap(inner, clock=clock, cache=cache, cache_ttl_seconds=0.0).search(_QUERY)
    assert inner.calls == 2


# --- Cache content / privacy --------------------------------------------------


def test_cache_keys_hold_only_the_scoped_sanitized_query() -> None:
    clock = _FakeClock()
    cache = SearchResultCache(clock=clock)
    inner = CountingSearchProvider()
    # A query carrying control characters (the shape sanitization exists to bound).
    _wrap(inner, clock=clock, cache=cache).search("Toppables\ncrackers\tCompliments")

    assert cache.keys() == ("searxng\nToppables crackers Compliments",)


def test_cache_is_bounded_and_evicts_the_oldest_entry() -> None:
    clock = _FakeClock()
    cache = SearchResultCache(max_entries=2, clock=clock)
    result = SearchResult(status=SearchStatus.PARTIAL)

    cache.put("a", result, ttl_seconds=60.0)
    cache.put("b", result, ttl_seconds=60.0)
    cache.put("c", result, ttl_seconds=60.0)

    assert cache.size == 2
    assert cache.get("a") is None
    assert cache.get("c") is result


def test_expired_entries_are_reaped_on_write() -> None:
    clock = _FakeClock()
    cache = SearchResultCache(clock=clock)
    cache.put("a", SearchResult(status=SearchStatus.PARTIAL), ttl_seconds=10.0)

    clock.advance(11.0)
    cache.put("b", SearchResult(status=SearchStatus.PARTIAL), ttl_seconds=10.0)

    assert cache.keys() == ("b",)


def test_hygiene_logs_carry_counts_and_statuses_but_no_query_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = _FakeClock()
    inner = CountingSearchProvider(
        per_query={_QUERY: SearchResult(status=SearchStatus.RATE_LIMITED)}
    )
    provider = _wrap(inner, clock=clock)

    with caplog.at_level(logging.DEBUG, logger="app.estimator.search_hygiene"):
        provider.search(_QUERY)
        provider.search(_OTHER_QUERY)

    assert caplog.records, "expected content-free search-hygiene telemetry"
    for record in caplog.records:
        rendered = record.getMessage() + repr(record.__dict__)
        assert "Toppables" not in rendered
        assert "hummus" not in rendered
        assert "reference.example.com" not in rendered
    statuses = {getattr(record, "search_status", None) for record in caplog.records}
    assert SearchStatus.RATE_LIMITED.value in statuses
    trips = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(trips) == 1
    assert trips[0].search_provider == "searxng"  # type: ignore[attr-defined]


# --- 429 cooldown -------------------------------------------------------------


def test_rate_limited_reply_trips_a_cooldown_that_stops_further_calls() -> None:
    clock = _FakeClock()
    cooldown = RateLimitCooldown(clock=clock)
    inner = CountingSearchProvider(SearchResult(status=SearchStatus.RATE_LIMITED))
    provider = _wrap(inner, clock=clock, cooldown=cooldown, cooldown_seconds=60.0)

    first = provider.search(_QUERY)
    during = provider.search(_OTHER_QUERY)

    assert first.status is SearchStatus.RATE_LIMITED
    # The second, *different* query never reaches the provider.
    assert during.status is SearchStatus.RATE_LIMITED
    assert during.candidates == ()
    assert inner.queries == [_QUERY]
    assert provider.stats.cooldown_trips == 1
    assert provider.stats.cooldown_skips == 1


def test_cooldown_spans_runs_and_expires_on_the_clock() -> None:
    clock = _FakeClock()
    cooldown = RateLimitCooldown(clock=clock)
    cache = SearchResultCache(clock=clock)
    inner = CountingSearchProvider(
        SearchResult(status=SearchStatus.SUCCESS, candidates=(_CANDIDATE,)),
        per_query={_QUERY: SearchResult(status=SearchStatus.RATE_LIMITED)},
    )

    _wrap(inner, clock=clock, cache=cache, cooldown=cooldown).search(_QUERY)
    assert inner.calls == 1

    # A later run inside the cooldown makes no call at all.
    during = _wrap(inner, clock=clock, cache=cache, cooldown=cooldown)
    assert during.search(_OTHER_QUERY).status is SearchStatus.RATE_LIMITED
    assert inner.calls == 1

    clock.advance(61.0)
    after = _wrap(inner, clock=clock, cache=cache, cooldown=cooldown)
    assert after.search(_OTHER_QUERY).status is SearchStatus.SUCCESS
    assert inner.calls == 2


def test_cached_answer_is_still_served_during_a_cooldown() -> None:
    # The cooldown bounds *egress*, not answers we already hold.
    clock = _FakeClock()
    cache = SearchResultCache(clock=clock)
    cooldown = RateLimitCooldown(clock=clock)
    inner = CountingSearchProvider(
        per_query={
            _QUERY: SearchResult(status=SearchStatus.SUCCESS, candidates=(_CANDIDATE,)),
            _OTHER_QUERY: SearchResult(status=SearchStatus.RATE_LIMITED),
        }
    )

    warm = _wrap(inner, clock=clock, cache=cache, cooldown=cooldown)
    warm.search(_QUERY)
    warm.search(_OTHER_QUERY)  # trips the cooldown
    assert inner.calls == 2

    later = _wrap(inner, clock=clock, cache=cache, cooldown=cooldown)
    assert later.search(_QUERY).status is SearchStatus.SUCCESS
    assert inner.calls == 2
    assert later.stats.cache_hits == 1


def test_zero_cooldown_disables_the_breaker() -> None:
    clock = _FakeClock()
    cooldown = RateLimitCooldown(clock=clock)
    inner = CountingSearchProvider(SearchResult(status=SearchStatus.RATE_LIMITED))
    provider = _wrap(inner, clock=clock, cooldown=cooldown, cooldown_seconds=0.0)

    provider.search(_QUERY)
    provider.search(_OTHER_QUERY)

    assert inner.calls == 2
    assert provider.stats.cooldown_trips == 0


# --- Delegation + factory wiring ---------------------------------------------


def test_wrapper_delegates_availability_and_capability() -> None:
    clock = _FakeClock()
    inner = CountingSearchProvider()
    provider = _wrap(inner, clock=clock)

    assert provider.enabled is True
    assert provider.available is True
    assert provider.capability == inner.capability
    assert provider.inner is inner


def test_factory_wires_the_configured_hygiene_bounds() -> None:
    settings = load_search_settings(
        {
            "SLACKS_SEARCH_CACHE_TTL_SECONDS": "42",
            "SLACKS_SEARCH_RATE_LIMIT_COOLDOWN_SECONDS": "7",
        }
    )
    provider = build_search_provider(settings)

    assert settings.cache_ttl_seconds == 42.0
    assert settings.rate_limit_cooldown_seconds == 7.0
    assert isinstance(provider, HygienicSearchProvider)
    assert isinstance(provider.inner, SearXNGSearchProvider)
    # The factory shares one process-wide cache/cooldown so the TTL cache and the
    # cooldown outlive a single run.
    assert provider.cache is shared_search_cache()
    assert provider.cooldown is shared_rate_limit_cooldown()


def test_hygiene_defaults_are_short_and_bounded() -> None:
    settings = SearchSettings()

    assert settings.cache_ttl_seconds == DEFAULT_SEARCH_CACHE_TTL_SECONDS
    assert settings.rate_limit_cooldown_seconds == DEFAULT_SEARCH_RATE_LIMIT_COOLDOWN_SECONDS
    assert 0 < settings.cache_ttl_seconds <= 900
    assert 0 < settings.rate_limit_cooldown_seconds <= 900
