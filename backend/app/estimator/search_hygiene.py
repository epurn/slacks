"""Search-call hygiene for the outbound search path (FTY-435).

The estimator's two web-evidence tiers each walk a bounded set of identity-query
variants per unresolved item (:data:`~app.estimator.branded_routing.MAX_IDENTITY_VARIANTS`),
and a multi-item event, a re-interpretation re-query, or a re-estimate after a
clarification answer replays those walks. Nothing upstream remembered an answer,
so a run could re-issue the *same* sanitized query several times, and a
:attr:`~app.estimator.search_models.SearchStatus.RATE_LIMITED` reply was treated
exactly like a miss — a throttled instance kept receiving the rest of the
variant/tier/item fan-out.

:class:`HygienicSearchProvider` is a decorator over any
:class:`~app.estimator.search_models.SearchProvider` that fixes both, at the one
place every search call already passes through:

1. **Per-run memo.** Every query the wrapper asked the provider is remembered for
   the life of the wrapper instance — which is one estimation run, because the
   production factory (:func:`~app.estimator.search_providers.build_search_provider`)
   is called once per worker attempt / request. A repeated sanitized query is
   answered from the memo with the *same* :class:`~app.estimator.search_models.SearchResult`
   DTO, so the downstream fetch/extract/evidence chain cannot tell a memo hit
   from a fresh call.
2. **Short-TTL shared cache.** Answered lookups (``success`` / ``partial``) are
   published to a small process-shared, TTL-bounded cache so the *next* run
   inside the TTL is served without egress. Failures are never published: a
   transient blip must not suppress search for later runs.
3. **429 cooldown.** A ``rate_limited`` reply trips a bounded, provider-scoped
   cooldown. While it is active, :meth:`HygienicSearchProvider.search` makes **no**
   provider call and returns ``rate_limited`` directly, which the resolver already
   treats as "this tier produced nothing" — it falls through to the next evidence
   tier and then model prior (FTY-062 fall-through), so the run still completes
   with honest provenance and never a user-visible failure.

**Why in-process and not Redis.** The dominant duplication is *within* one run
(the overlapping variant walks of both tiers, a re-query, repeated identities in
one event), which the per-instance memo captures completely without any network
hop. The cross-run win is the small tail — the same food logged again, or a
re-estimate after a clarification answer — which a process-shared TTL cache
already serves for the worker that handles it. A Redis round-trip per search would
add a hop on the hot path and, more importantly, move search results and product
data into a *durable* store (a new retention surface, and Redis is the shared
broker) to buy that tail; process memory with a bounded TTL and a bounded entry
count is the cheaper and privacy-preferable trade. The cooldown is likewise
per-process: with several workers each trips on its own first 429, which still
removes the fan-out that caused the throttling.

**Privacy.** Cache and memo keys are the **sanitized** query only (the exact
string that already egresses, via the :func:`~app.estimator.search_sanitization.sanitize_query`
chokepoint), scoped by the provider key; values are provider
:class:`~app.estimator.search_models.SearchResult` DTOs (candidate URLs, bounded
titles/snippets). No raw diary text, no personal context, no credential ever
reaches either. Entries expire on a bounded TTL and the cache is size-capped, so
stale product data cannot linger. Telemetry is counts and closed-vocabulary
statuses — query text is never logged.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from app.estimator.search_models import (
    SearchCapability,
    SearchProvider,
    SearchResult,
    SearchStatus,
)
from app.estimator.search_sanitization import sanitize_query

logger = logging.getLogger(__name__)

#: Default lifetime of a shared-cache entry. Short by design: long enough to cover a
#: re-estimate after a clarification answer and a repeat log of the same food within a
#: session, short enough that a product page's facts cannot go stale in the cache. A
#: documented tunable (``SLACKS_SEARCH_CACHE_TTL_SECONDS``); ``0`` disables the shared
#: cache, leaving only the per-run memo.
DEFAULT_SEARCH_CACHE_TTL_SECONDS: Final[float] = 300.0

#: Default cooldown applied after a ``rate_limited`` reply, during which no search call
#: egresses. Long enough for an upstream throttle window to clear, short enough that the
#: next log's evidence tiers are usable again. A documented tunable
#: (``SLACKS_SEARCH_RATE_LIMIT_COOLDOWN_SECONDS``); ``0`` disables the cooldown.
DEFAULT_SEARCH_RATE_LIMIT_COOLDOWN_SECONDS: Final[float] = 60.0

#: Hard cap on shared-cache entries. Bounds how much provider result data lives in
#: process memory at once; the oldest entry is evicted past the cap.
DEFAULT_SEARCH_CACHE_MAX_ENTRIES: Final[int] = 512

#: Hard cap on per-run memo entries. A run's query set is already bounded by the run
#: budget and the identity-variant cap; this is the structural backstop.
MAX_RUN_MEMO_ENTRIES: Final[int] = 256

#: Statuses that count as an *answer* from the provider and may be published to the
#: cross-run shared cache: a usable candidate list, or an authoritative "nothing
#: usable here". Everything else (``failed`` / ``rate_limited`` / ``disabled`` /
#: ``unavailable``) is a transport or config outcome, never cached across runs, so a
#: blip or a throttle window cannot suppress search for a later run.
CACHEABLE_STATUSES: Final[frozenset[SearchStatus]] = frozenset(
    {SearchStatus.SUCCESS, SearchStatus.PARTIAL}
)

#: Content-free telemetry labels for how one search call was served.
_OUTCOME_MEMO_HIT = "memo_hit"
_OUTCOME_CACHE_HIT = "cache_hit"
_OUTCOME_COOLDOWN_SKIP = "cooldown_skip"
_OUTCOME_PROVIDER_CALL = "provider_call"


@dataclass
class SearchCallStats:
    """Content-free counters for how a wrapper's search calls were served (FTY-435).

    Counts only — no query text, no URLs. Read by tests and available for a
    caller that wants to log a per-run summary.
    """

    provider_calls: int = 0
    memo_hits: int = 0
    cache_hits: int = 0
    cooldown_skips: int = 0
    cooldown_trips: int = 0

    @property
    def served_without_egress(self) -> int:
        """Search calls answered with no provider call at all."""

        return self.memo_hits + self.cache_hits + self.cooldown_skips


class SearchResultCache:
    """A small, TTL-bounded, size-capped store of answered search lookups.

    Keys are ``"<provider scope>\\n<sanitized query>"``; values are provider
    :class:`SearchResult` DTOs. The clock is injectable so TTL expiry is tested
    deterministically with no wall-clock wait.
    """

    def __init__(
        self,
        *,
        max_entries: int = DEFAULT_SEARCH_CACHE_MAX_ENTRIES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_entries = max_entries
        self._clock = clock
        # Insertion-ordered, so the oldest entry is the first key past the cap.
        self._entries: dict[str, tuple[float, SearchResult]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> SearchResult | None:
        """The cached result for ``key``, or ``None`` when absent or expired."""

        now = self._clock()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return None
            expires_at, result = entry
            if expires_at <= now:
                del self._entries[key]
                return None
            return result

    def put(self, key: str, result: SearchResult, *, ttl_seconds: float) -> None:
        """Store ``result`` under ``key`` for ``ttl_seconds``; a non-positive TTL is a no-op."""

        if ttl_seconds <= 0:
            return
        now = self._clock()
        with self._lock:
            self._entries.pop(key, None)
            self._entries[key] = (now + ttl_seconds, result)
            self._evict_locked(now)

    def clear(self) -> None:
        """Drop every entry (process shutdown / test isolation)."""

        with self._lock:
            self._entries.clear()

    @property
    def size(self) -> int:
        """Current entry count, including entries not yet reaped (test/introspection)."""

        with self._lock:
            return len(self._entries)

    def keys(self) -> tuple[str, ...]:
        """The current cache keys, for privacy assertions (test/introspection)."""

        with self._lock:
            return tuple(self._entries)

    def _evict_locked(self, now: float) -> None:
        """Reap expired entries, then oldest-first until the cap holds."""

        for key in [key for key, (expires_at, _) in self._entries.items() if expires_at <= now]:
            del self._entries[key]
        while len(self._entries) > self._max_entries:
            del self._entries[next(iter(self._entries))]


class RateLimitCooldown:
    """A bounded, provider-scoped stop on search calls after a rate-limit reply.

    Deliberately *not* a full circuit breaker: there is no half-open probe and no
    failure counter. One ``rate_limited`` reply is an authoritative signal that the
    instance is being throttled right now, so search pauses for a fixed window and
    the resolver's existing provider-unavailable fall-through carries the run.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._until: dict[str, float] = {}
        self._lock = threading.Lock()

    def active(self, scope: str) -> bool:
        """Whether ``scope``'s cooldown is still running."""

        now = self._clock()
        with self._lock:
            until = self._until.get(scope)
            if until is None:
                return False
            if until <= now:
                del self._until[scope]
                return False
            return True

    def trip(self, scope: str, *, cooldown_seconds: float) -> bool:
        """Start (or extend) ``scope``'s cooldown; ``False`` when disabled by config."""

        if cooldown_seconds <= 0:
            return False
        now = self._clock()
        with self._lock:
            self._until[scope] = max(self._until.get(scope, now), now) + cooldown_seconds
        return True

    def clear(self) -> None:
        """Drop every cooldown (process shutdown / test isolation)."""

        with self._lock:
            self._until.clear()


#: The process-shared cache/cooldown the production factory hands every wrapper, so
#: the cross-run TTL cache and the 429 cooldown outlive one run. Injectable per
#: wrapper for tests; :func:`reset_search_hygiene` resets both between tests.
_SHARED_CACHE = SearchResultCache()
_SHARED_COOLDOWN = RateLimitCooldown()


def shared_search_cache() -> SearchResultCache:
    """The process-shared answered-lookup cache."""

    return _SHARED_CACHE


def shared_rate_limit_cooldown() -> RateLimitCooldown:
    """The process-shared search rate-limit cooldown."""

    return _SHARED_COOLDOWN


def reset_search_hygiene() -> None:
    """Clear the process-shared cache and cooldown (test isolation)."""

    _SHARED_CACHE.clear()
    _SHARED_COOLDOWN.clear()


class HygienicSearchProvider:
    """Wrap a search provider with per-run dedup, a short-TTL cache, and a 429 cooldown.

    Availability/capability delegate to ``inner`` unchanged, so diagnostics
    (``GET /healthz/sources``) and the resolver's tier-availability checks see exactly
    the configured backend. Only :meth:`search` differs, and only by *not* making calls
    it can answer another way.
    """

    def __init__(
        self,
        inner: SearchProvider,
        *,
        scope: str = "",
        cache_ttl_seconds: float = DEFAULT_SEARCH_CACHE_TTL_SECONDS,
        cooldown_seconds: float = DEFAULT_SEARCH_RATE_LIMIT_COOLDOWN_SECONDS,
        cache: SearchResultCache | None = None,
        cooldown: RateLimitCooldown | None = None,
    ) -> None:
        self._inner = inner
        self._scope = scope
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cooldown_seconds = cooldown_seconds
        self._cache = shared_search_cache() if cache is None else cache
        self._cooldown = shared_rate_limit_cooldown() if cooldown is None else cooldown
        self._memo: dict[str, SearchResult] = {}
        self._lock = threading.Lock()
        self.stats = SearchCallStats()

    @property
    def inner(self) -> SearchProvider:
        """The wrapped backend adapter (diagnostics / tests)."""

        return self._inner

    @property
    def cache(self) -> SearchResultCache:
        """The answered-lookup cache backing this wrapper (introspection / tests)."""

        return self._cache

    @property
    def cooldown(self) -> RateLimitCooldown:
        """The rate-limit cooldown backing this wrapper (introspection / tests)."""

        return self._cooldown

    @property
    def enabled(self) -> bool:
        return self._inner.enabled

    @property
    def available(self) -> bool:
        return self._inner.available

    @property
    def capability(self) -> SearchCapability:
        return self._inner.capability

    def search(self, query: str) -> SearchResult:
        """Answer ``query`` from the memo/cache when possible, else call the provider.

        A memo or cache hit returns the identical :class:`SearchResult` the provider
        gave, so the downstream chain (fetch → extract → evidence/provenance) is
        unchanged. During a cooldown no call is made and ``rate_limited`` is returned,
        which the resolver already handles as "this tier produced nothing".
        """

        sanitized = sanitize_query(query)
        if not sanitized:
            # An empty sanitized query never egresses (the adapter answers ``partial``
            # at its own chokepoint); nothing to key a cache entry on.
            return self._inner.search(query)

        memoized = self._memoized(sanitized)
        if memoized is not None:
            self.stats.memo_hits += 1
            self._log(_OUTCOME_MEMO_HIT, memoized.status)
            return memoized

        key = self._cache_key(sanitized)
        cached = self._cache.get(key)
        if cached is not None:
            self.stats.cache_hits += 1
            self._remember(sanitized, cached)
            self._log(_OUTCOME_CACHE_HIT, cached.status)
            return cached

        if self._cooldown.active(self._scope):
            self.stats.cooldown_skips += 1
            self._log(_OUTCOME_COOLDOWN_SKIP, SearchStatus.RATE_LIMITED)
            return SearchResult(status=SearchStatus.RATE_LIMITED)

        result = self._inner.search(query)
        self.stats.provider_calls += 1
        self._remember(sanitized, result)
        if result.status in CACHEABLE_STATUSES:
            self._cache.put(key, result, ttl_seconds=self._cache_ttl_seconds)
        if result.status is SearchStatus.RATE_LIMITED and self._cooldown.trip(
            self._scope, cooldown_seconds=self._cooldown_seconds
        ):
            self.stats.cooldown_trips += 1
            logger.warning(
                "search provider rate limited; pausing search calls",
                extra={
                    "search_provider": self._scope,
                    "cooldown_seconds": self._cooldown_seconds,
                    "search_provider_calls": self.stats.provider_calls,
                },
            )
        self._log(_OUTCOME_PROVIDER_CALL, result.status)
        return result

    def _cache_key(self, sanitized: str) -> str:
        """The shared-cache key: the provider scope plus the sanitized query only."""

        return f"{self._scope}\n{sanitized}"

    def _memoized(self, sanitized: str) -> SearchResult | None:
        with self._lock:
            return self._memo.get(sanitized)

    def _remember(self, sanitized: str, result: SearchResult) -> None:
        with self._lock:
            if len(self._memo) < MAX_RUN_MEMO_ENTRIES or sanitized in self._memo:
                self._memo[sanitized] = result

    def _log(self, outcome: str, status: SearchStatus) -> None:
        """Record one content-free search-hygiene decision (counts + statuses only)."""

        logger.debug(
            "search call served",
            extra={
                "search_provider": self._scope,
                "search_outcome": outcome,
                "search_status": status.value,
                "search_provider_calls": self.stats.provider_calls,
                "search_calls_without_egress": self.stats.served_without_egress,
            },
        )
