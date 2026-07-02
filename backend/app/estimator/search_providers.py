"""Official-source search provider transport, parsing, and factory."""

from __future__ import annotations

import socket
from typing import Any, Final, Protocol
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    FetchTransientError,
    Resolver,
    get_json,
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
from app.estimator.search_sanitization import sanitize_query
from app.estimator.search_settings import (
    BRAVE_PROVIDER,
    NONE_PROVIDER,
    SEARXNG_PROVIDER,
    SearchSettings,
    load_search_settings,
)

#: Brave carries the subscription key in this request header (never the query
#: string), so it cannot leak through a logged URL.
_BRAVE_KEY_HEADER = "X-Subscription-Token"

#: Bound the (untrusted) candidate title we surface from the provider payload.
_MAX_TITLE_LEN: Final[int] = 300

#: The HTTP status a provider returns to signal a rate-limit / quota exhaustion.
_RATE_LIMITED_STATUS: Final[int] = 429

#: Result URLs eligible for the (separate, FTY-078) fetch step must be HTTP(S).
_FETCHABLE_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})


class BraveResult(BaseModel):
    """A single Brave web result (untrusted; only ``url`` + ``title`` are used)."""

    model_config = ConfigDict(extra="ignore")

    url: str = ""
    title: str = ""

    @field_validator("title", mode="before")
    @classmethod
    def _truncate_title(cls, value: Any) -> Any:
        """Truncate (not reject) an overlong title."""

        if isinstance(value, str):
            return value[:_MAX_TITLE_LEN]
        return value


class BraveWeb(BaseModel):
    """The ``web`` block of a Brave search reply (untrusted; extras ignored)."""

    model_config = ConfigDict(extra="ignore")

    results: list[BraveResult] = Field(default_factory=list)


class BraveResponse(BaseModel):
    """The validated shape of a Brave ``/res/v1/web/search`` reply."""

    model_config = ConfigDict(extra="ignore")

    web: BraveWeb | None = None


class SearXNGResult(BaseModel):
    """A single SearXNG result (untrusted; only ``url`` + ``title`` are used)."""

    model_config = ConfigDict(extra="ignore")

    url: str = ""
    title: str = ""

    @field_validator("title", mode="before")
    @classmethod
    def _truncate_title(cls, value: Any) -> Any:
        """Truncate (not reject) an overlong title — same guard as Brave's."""

        if isinstance(value, str):
            return value[:_MAX_TITLE_LEN]
        return value


class SearXNGResponse(BaseModel):
    """The validated shape of a SearXNG ``/search?format=json`` reply."""

    model_config = ConfigDict(extra="ignore")

    results: list[SearXNGResult] = Field(default_factory=list)


# Transport callable signature, injectable so tests drive a network-free fake.
class _Transport(Protocol):
    def __call__(
        self,
        url: str,
        *,
        headers: dict[str, str],
        timeout_seconds: float,
        allowed_hosts: frozenset[str],
        resolver: Resolver,
        local_http_hosts: frozenset[str],
    ) -> dict[str, Any]: ...


def _default_transport(
    url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: float,
    allowed_hosts: frozenset[str],
    resolver: Resolver,
    local_http_hosts: frozenset[str],
) -> dict[str, Any]:
    return get_json(
        url,
        headers=headers,
        timeout_seconds=timeout_seconds,
        allowed_hosts=allowed_hosts,
        resolver=resolver,
        local_http_hosts=local_http_hosts,
    )


class BraveSearchProvider:
    """Hardened, allowlisted Brave Search adapter — the explicit opt-in keyed backend.

    Sends only the sanitized item-identity query (no personal context) with the API
    key in the ``X-Subscription-Token`` header. The ``transport`` and ``resolver``
    seams let tests exercise the full mapping with no network or DNS.
    """

    def __init__(
        self,
        settings: SearchSettings,
        *,
        transport: _Transport = _default_transport,
        resolver: Resolver | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._resolver = resolver or socket.getaddrinfo

    @property
    def enabled(self) -> bool:
        return self._settings.is_enabled

    @property
    def available(self) -> bool:
        return self._settings.is_available

    @property
    def capability(self) -> SearchCapability:
        return SearchCapability(
            id=OFFICIAL_SOURCE,
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=SEARCH_KINDS,
            enabled=self._settings.is_enabled,
            available=self._settings.is_available,
        )

    def search(self, query: str) -> SearchResult:
        """Search the provider for ``query`` and return candidate URLs + a status."""

        if not self._settings.is_enabled:
            return SearchResult(status=SearchStatus.DISABLED)
        api_key = self._settings.api_key
        if api_key is None or not self._settings.is_available:
            return SearchResult(status=SearchStatus.UNAVAILABLE)

        sanitized = sanitize_query(query)
        if not sanitized:
            return SearchResult(status=SearchStatus.PARTIAL)

        headers = {_BRAVE_KEY_HEADER: api_key.get_secret_value()}
        try:
            raw = self._transport(
                self._settings.query_url(sanitized),
                headers=headers,
                timeout_seconds=self._settings.timeout_seconds,
                allowed_hosts=self._settings.allowed_hosts,
                resolver=self._resolver,
                local_http_hosts=frozenset(),
            )
        except FetchTransientError:
            return SearchResult(status=SearchStatus.FAILED)
        except FetchResponseError as exc:
            if exc.status_code == _RATE_LIMITED_STATUS:
                return SearchResult(status=SearchStatus.RATE_LIMITED)
            return SearchResult(status=SearchStatus.FAILED)
        except FetchPolicyError:
            return SearchResult(status=SearchStatus.FAILED)

        try:
            response = BraveResponse.model_validate(raw)
            web = response.web
            candidates = _map_candidates(
                web.results if web is not None else [], self._settings.max_results
            )
        except ValidationError:
            return SearchResult(status=SearchStatus.FAILED)
        if not candidates:
            return SearchResult(status=SearchStatus.PARTIAL)
        return SearchResult(status=SearchStatus.SUCCESS, candidates=tuple(candidates))


class SearXNGSearchProvider:
    """Hardened, allowlisted SearXNG adapter — the keyless default backend.

    Queries a local/self-hosted SearXNG instance's JSON API with no credential at
    all: the request carries only the sanitized item-identity query and
    ``format=json``. Egress goes through the hardened fetcher; a local plain-HTTP
    base URL rides the narrow ``local_http_hosts`` exception.
    """

    def __init__(
        self,
        settings: SearchSettings,
        *,
        transport: _Transport = _default_transport,
        resolver: Resolver | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._resolver = resolver or socket.getaddrinfo

    @property
    def enabled(self) -> bool:
        return self._settings.is_enabled

    @property
    def available(self) -> bool:
        return self._settings.is_available

    @property
    def capability(self) -> SearchCapability:
        return SearchCapability(
            id=OFFICIAL_SOURCE,
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=SEARCH_KINDS,
            enabled=self._settings.is_enabled,
            available=self._settings.is_available,
        )

    def search(self, query: str) -> SearchResult:
        """Search the instance for ``query`` and return candidate URLs + a status."""

        if not self._settings.is_enabled:
            return SearchResult(status=SearchStatus.DISABLED)

        sanitized = sanitize_query(query)
        if not sanitized:
            return SearchResult(status=SearchStatus.PARTIAL)

        try:
            raw = self._transport(
                self._settings.query_url(sanitized),
                headers={},
                timeout_seconds=self._settings.timeout_seconds,
                allowed_hosts=self._settings.allowed_hosts,
                resolver=self._resolver,
                local_http_hosts=self._settings.local_http_hosts,
            )
        except FetchTransientError:
            return SearchResult(status=SearchStatus.FAILED)
        except FetchResponseError as exc:
            if exc.status_code == _RATE_LIMITED_STATUS:
                return SearchResult(status=SearchStatus.RATE_LIMITED)
            return SearchResult(status=SearchStatus.FAILED)
        except FetchPolicyError:
            return SearchResult(status=SearchStatus.FAILED)

        try:
            response = SearXNGResponse.model_validate(raw)
            candidates = _map_candidates(response.results, self._settings.max_results)
        except ValidationError:
            return SearchResult(status=SearchStatus.FAILED)
        if not candidates:
            return SearchResult(status=SearchStatus.PARTIAL)
        return SearchResult(status=SearchStatus.SUCCESS, candidates=tuple(candidates))


class NullSearchProvider:
    """The ``none`` backend: search explicitly turned off by the operator."""

    def __init__(self, settings: SearchSettings) -> None:
        self._settings = settings

    @property
    def enabled(self) -> bool:
        return False

    @property
    def available(self) -> bool:
        return False

    @property
    def capability(self) -> SearchCapability:
        return SearchCapability(
            id=OFFICIAL_SOURCE,
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=SEARCH_KINDS,
            enabled=False,
            available=False,
        )

    def search(self, query: str) -> SearchResult:
        return SearchResult(status=SearchStatus.DISABLED)


def _map_candidates(
    results: list[BraveResult] | list[SearXNGResult], max_results: int
) -> list[SearchCandidate]:
    """Map provider results to fetchable candidate URLs, bounded by ``max_results``."""

    candidates: list[SearchCandidate] = []
    for result in results:
        url = result.url.strip()
        if urlsplit(url).scheme.lower() not in _FETCHABLE_SCHEMES:
            continue
        candidates.append(SearchCandidate(url=url, title=result.title))
        if len(candidates) >= max_results:
            break
    return candidates


def build_search_provider(settings: SearchSettings | None = None) -> SearchProvider:
    """Build the configured :class:`SearchProvider` from environment-loaded settings."""

    resolved = settings or load_search_settings()
    if resolved.provider == SEARXNG_PROVIDER:
        return SearXNGSearchProvider(resolved)
    if resolved.provider == BRAVE_PROVIDER:
        return BraveSearchProvider(resolved)
    if resolved.provider == NONE_PROVIDER:
        return NullSearchProvider(resolved)
    # Unreachable: SearchSettings validates ``provider`` against KNOWN_PROVIDERS.
    raise ValueError(f"unsupported search provider: {resolved.provider}")
