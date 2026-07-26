"""Compatibility facade for the official-source search-provider adapter.

The implementation is split across estimator-local modules so the egress boundary
stays reviewable:

- :mod:`app.estimator.search_models` owns public DTOs and the provider protocol.
- :mod:`app.estimator.search_settings` owns environment parsing and base-URL policy.
- :mod:`app.estimator.search_sanitization` owns query sanitization.
- :mod:`app.estimator.search_providers` owns provider-specific parsing and transport.
- :mod:`app.estimator.search_hygiene` owns call hygiene: per-run query dedup, the
  short-TTL answered-lookup cache, and the ``429`` cooldown (FTY-435).

This module preserves the original public import surface used by tests and
pipeline code.
"""

from __future__ import annotations

from app.estimator.search_hygiene import (
    CACHEABLE_STATUSES,
    DEFAULT_SEARCH_CACHE_MAX_ENTRIES,
    DEFAULT_SEARCH_CACHE_TTL_SECONDS,
    DEFAULT_SEARCH_RATE_LIMIT_COOLDOWN_SECONDS,
    HygienicSearchProvider,
    RateLimitCooldown,
    SearchCallStats,
    SearchResultCache,
    reset_search_hygiene,
    shared_rate_limit_cooldown,
    shared_search_cache,
)
from app.estimator.search_models import (
    OFFICIAL_SOURCE,
    OFFICIAL_SOURCE_TYPE,
    SEARCH_KINDS,
    SearchCandidate,
    SearchCapability,
    SearchProvider,
    SearchResult,
    SearchStatus,
)
from app.estimator.search_providers import (
    BraveResponse,
    BraveResult,
    BraveSearchProvider,
    BraveWeb,
    NullSearchProvider,
    SearXNGResponse,
    SearXNGResult,
    SearXNGSearchProvider,
    build_search_provider,
)
from app.estimator.search_sanitization import (
    LOCAL_SEARXNG_HTTP_HOSTS,
    MAX_QUERY_LEN,
    sanitize_query,
)
from app.estimator.search_sanitization import (
    is_local_search_host as _is_local_search_host,
)
from app.estimator.search_settings import (
    BRAVE_PROVIDER,
    DEFAULT_BRAVE_BASE_URL,
    DEFAULT_SEARXNG_BASE_URL,
    ENV_PREFIX,
    KNOWN_PROVIDERS,
    NONE_PROVIDER,
    SEARXNG_PROVIDER,
    SearchSettings,
    load_search_settings,
)

__all__ = [
    "BRAVE_PROVIDER",
    "CACHEABLE_STATUSES",
    "DEFAULT_BRAVE_BASE_URL",
    "DEFAULT_SEARCH_CACHE_MAX_ENTRIES",
    "DEFAULT_SEARCH_CACHE_TTL_SECONDS",
    "DEFAULT_SEARCH_RATE_LIMIT_COOLDOWN_SECONDS",
    "DEFAULT_SEARXNG_BASE_URL",
    "ENV_PREFIX",
    "KNOWN_PROVIDERS",
    "LOCAL_SEARXNG_HTTP_HOSTS",
    "MAX_QUERY_LEN",
    "NONE_PROVIDER",
    "OFFICIAL_SOURCE",
    "OFFICIAL_SOURCE_TYPE",
    "SEARCH_KINDS",
    "SEARXNG_PROVIDER",
    "BraveResponse",
    "BraveResult",
    "BraveSearchProvider",
    "BraveWeb",
    "HygienicSearchProvider",
    "NullSearchProvider",
    "RateLimitCooldown",
    "SearXNGResponse",
    "SearXNGResult",
    "SearXNGSearchProvider",
    "SearchCallStats",
    "SearchCandidate",
    "SearchCapability",
    "SearchProvider",
    "SearchResult",
    "SearchResultCache",
    "SearchSettings",
    "SearchStatus",
    "_is_local_search_host",
    "build_search_provider",
    "load_search_settings",
    "reset_search_hygiene",
    "sanitize_query",
    "shared_rate_limit_cooldown",
    "shared_search_cache",
]
