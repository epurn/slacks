"""Compatibility facade for the official-source search-provider adapter.

The implementation is split across estimator-local modules so the egress boundary
stays reviewable:

- :mod:`app.estimator.search_models` owns public DTOs and the provider protocol.
- :mod:`app.estimator.search_settings` owns environment parsing and base-URL policy.
- :mod:`app.estimator.search_sanitization` owns query sanitization.
- :mod:`app.estimator.search_providers` owns provider-specific parsing and transport.

This module preserves the original public import surface used by tests and
pipeline code.
"""

from __future__ import annotations

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
    "DEFAULT_BRAVE_BASE_URL",
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
    "NullSearchProvider",
    "SearXNGResponse",
    "SearXNGResult",
    "SearchCandidate",
    "SearchCapability",
    "SearchProvider",
    "SearchResult",
    "SearchSettings",
    "SearchStatus",
    "SearXNGSearchProvider",
    "_is_local_search_host",
    "build_search_provider",
    "load_search_settings",
    "sanitize_query",
]
