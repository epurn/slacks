"""Pluggable official-source search-provider adapter (FTY-079).

This is the **search half** of the ``official_source`` tier in the
evidence-retrieval source hierarchy (``docs/contracts/evidence-retrieval.md``). It
takes a **sanitized item-identity query** (product / restaurant / manufacturer
name) and returns a bounded list of candidate result URLs plus an explicit lookup
**status**, sending **no personal context** to the provider. It ships no fetcher
and no resolution pipeline of its own: the hardened fetcher for the result URLs is
FTY-078, and the official-source resolution step that consumes the candidates is
FTY-062. This adapter is the search-boundary prerequisite for both.

Design, mirroring the FDC / OFF evidence adapters:

- **Pluggable.** :class:`SearchProvider` is the adapter interface; **Brave Search**
  is the default (and only) backend in v1, selected by ``FATTY_SEARCH_PROVIDER``.
  A different backend can be registered later without re-deciding this boundary.
- **Disabled by default for self-host.** No key is bundled, so out of the box the
  adapter reports :attr:`SearchStatus.UNAVAILABLE` and callers (FTY-062) fall
  through to the model-prior-with-status path. A self-hoster supplies
  ``FATTY_SEARCH_API_KEY`` to enable it; ``FATTY_SEARCH_ENABLED=false`` turns it
  off explicitly (:attr:`SearchStatus.DISABLED`) even if a key is present.
- **Status surface.** Every lookup resolves to exactly one
  :class:`SearchStatus`, aligned with the FTY-045 evidence-retrieval status
  vocabulary (``disabled`` / ``unavailable`` / ``rate_limited`` / ``failed`` /
  ``partial`` / ``success``), and the capability/availability signal is reflected
  in ``GET /healthz/sources`` diagnostics.
- **Query sanitization / data minimization.** :func:`sanitize_query` is the single
  chokepoint every query passes through before egress: control characters are
  stripped, whitespace collapsed, and the string length-bounded. The adapter's
  request shape is closed to exactly ``q`` + ``count`` — there is no channel for
  profile, weight, food history, or event metadata to reach the provider.
- **Secret handling.** The API key is a :class:`~pydantic.SecretStr` read from the
  environment only, never exposed to clients, never logged, and carried in the
  ``X-Subscription-Token`` **header** (never the query string), so it cannot leak
  through a logged URL.
- **Content-free errors.** Transport failures are mapped to a status, never to an
  exception that echoes the query, key, headers, or response body.
"""

from __future__ import annotations

import os
import re
import socket
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final, Protocol, runtime_checkable
from urllib.parse import urlencode, urlsplit

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from app.estimator.hardened_fetch import (
    FetchPolicyError,
    FetchResponseError,
    FetchTransientError,
    Resolver,
    get_json,
)

#: Search settings are read from variables with this prefix, e.g.
#: ``FATTY_SEARCH_API_KEY``.
ENV_PREFIX = "FATTY_SEARCH_"

#: The default (and v1-only) search backend.
BRAVE_PROVIDER = "brave"

#: Known, registered search backends. Adding a provider means registering its key
#: here and a :class:`SearchProvider` adapter for it.
KNOWN_PROVIDERS: Final[frozenset[str]] = frozenset({BRAVE_PROVIDER})

#: Default Brave Search API base. Overridable for self-host proxies/mirrors via env.
DEFAULT_BRAVE_BASE_URL = "https://api.search.brave.com"

#: Brave's web-search path appended to the base URL.
_BRAVE_SEARCH_PATH = "/res/v1/web/search"

#: Brave carries the subscription key in this request header (never the query
#: string), so it cannot leak through a logged URL.
_BRAVE_KEY_HEADER = "X-Subscription-Token"

#: Source-system id for the official-source tier (``docs/contracts/evidence-retrieval.md``
#: Version section). The configured search backend feeds this hierarchy slot.
OFFICIAL_SOURCE = "official_source"

#: Source-hierarchy classification recorded on official-source evidence rows.
OFFICIAL_SOURCE_TYPE = "official_source"

#: Lookup kinds the official-source search serves.
SEARCH_KINDS: Final[tuple[str, ...]] = ("named_product", "restaurant_item")

#: Upper bound on a sanitized query before egress. Item identity is short; a longer
#: string is a sign of smuggled context and is truncated at the chokepoint.
MAX_QUERY_LEN: Final[int] = 256

#: Bound the (untrusted) candidate title we surface from the provider payload.
_MAX_TITLE_LEN: Final[int] = 300

#: The HTTP status a provider returns to signal a rate-limit / quota exhaustion.
_RATE_LIMITED_STATUS: Final[int] = 429

#: Control characters (incl. newlines/tabs) are stripped before egress so a query
#: cannot smuggle multi-line / structured personal context past the chokepoint.
_CONTROL_CHARS_RE: Final[re.Pattern[str]] = re.compile(r"[\x00-\x1f\x7f]")

#: Collapse any run of whitespace to a single space.
_WHITESPACE_RE: Final[re.Pattern[str]] = re.compile(r"\s+")

#: Result URLs eligible for the (separate, FTY-078) fetch step must be HTTP(S).
_FETCHABLE_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})


class SearchStatus(StrEnum):
    """The outcome of one search lookup, aligned with the FTY-045 status vocabulary.

    These are the values the adapter surfaces to its caller (FTY-062), mapping
    cleanly onto the evidence-retrieval ``Provider Capability / Status`` table:

    - :attr:`DISABLED` — provider turned off by self-host config.
    - :attr:`UNAVAILABLE` — provider not configured / missing credentials.
    - :attr:`RATE_LIMITED` — provider returned a rate-limit / quota signal.
    - :attr:`FAILED` — timeout, connection error, 5xx, 4xx, non-conforming, or
      policy-blocked response; nothing from this lookup is trusted.
    - :attr:`PARTIAL` — the provider answered but yielded no usable candidate URL.
    - :attr:`SUCCESS` — a usable list of candidate result URLs was returned.
    """

    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    RATE_LIMITED = "rate_limited"
    FAILED = "failed"
    PARTIAL = "partial"
    SUCCESS = "success"


@dataclass(frozen=True)
class SearchCandidate:
    """One candidate official-source result: a fetchable URL and its display title.

    Treated as **untrusted** by the caller — the URL is a candidate for the
    hardened fetch step (FTY-078), and the title is never trusted as nutrition
    facts.
    """

    url: str
    title: str


@dataclass(frozen=True)
class SearchResult:
    """A search lookup's explicit status plus its (possibly empty) candidate list.

    ``candidates`` is non-empty only for :attr:`SearchStatus.SUCCESS`; every other
    status carries no candidates, so a caller can never mistake an off/failed
    lookup for a result.
    """

    status: SearchStatus
    candidates: tuple[SearchCandidate, ...] = ()


@dataclass(frozen=True)
class SearchCapability:
    """The search provider's static capability descriptor for diagnostics.

    Mirrors the evidence-retrieval **Provider Capability** contract so health/config
    diagnostics can surface provider state without a trial call. Carries no secret.
    """

    id: str
    source_type: str
    kinds: tuple[str, ...]
    enabled: bool
    available: bool


def sanitize_query(query: str) -> str:
    """Return the single sanitized query string that may egress to the provider.

    The **single chokepoint** for data minimization: strips control characters
    (which could smuggle multi-line / structured personal context), collapses
    whitespace, and length-bounds the result. Only item identity reaches this
    function; the adapter never accepts profile, weight, history, or event
    metadata, so the closed ``q`` + ``count`` request shape cannot carry them.
    """

    no_control = _CONTROL_CHARS_RE.sub(" ", query)
    collapsed = _WHITESPACE_RE.sub(" ", no_control).strip()
    return collapsed[:MAX_QUERY_LEN]


class SearchSettings(BaseModel):
    """Validated search-provider config, read from ``FATTY_SEARCH_`` env vars.

    Frozen and ``extra="forbid"`` so config is immutable and unknown keys are
    rejected. The base URL must be ``https`` (the hardened fetch refuses anything
    else); the host is derived from it for the request allowlist. No key is bundled,
    so the adapter is unavailable (search disabled in effect) out of the box.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Which registered backend to use. ``brave`` is the v1 default.
    provider: str = BRAVE_PROVIDER
    #: Self-host enable/disable flag. On by default, but a missing key still leaves
    #: the adapter unavailable; set ``false`` to turn the source off explicitly.
    enabled: bool = True
    #: Provider API key (secret). **Absent → source unavailable** (disabled by
    #: default for self-host). Read from env only; never logged or sent to clients.
    api_key: SecretStr | None = None
    base_url: str = DEFAULT_BRAVE_BASE_URL
    #: Per-request wall-clock timeout. A documented tunable.
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    #: Number of candidate result URLs requested / surfaced.
    max_results: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="after")
    def _validate(self) -> SearchSettings:
        """Fail closed on an unknown provider or a non-https base URL."""

        if self.provider not in KNOWN_PROVIDERS:
            raise ValueError(f"FATTY_SEARCH_PROVIDER must be one of {sorted(KNOWN_PROVIDERS)}")
        if not self.base_url.lower().startswith("https://"):
            raise ValueError("FATTY_SEARCH_BASE_URL must be an https URL")
        return self

    @property
    def is_available(self) -> bool:
        """Whether the required credentials are present (the adapter may be queried)."""

        return self.api_key is not None and bool(self.api_key.get_secret_value())

    @property
    def search_url(self) -> str:
        """The provider's web-search endpoint for the configured base URL."""

        return f"{self.base_url.rstrip('/')}{_BRAVE_SEARCH_PATH}"

    def query_url(self, sanitized_query: str) -> str:
        """The full search URL for ``sanitized_query`` (key is **not** in the URL).

        Only ``q`` (the sanitized item identity) and ``count`` ride in the query
        string; the API key always travels in the request header.
        """

        params = urlencode({"q": sanitized_query, "count": self.max_results})
        return f"{self.search_url}?{params}"

    @property
    def allowed_hosts(self) -> frozenset[str]:
        """The single allowlisted host (derived from the base URL) for fetches."""

        host = urlsplit(self.base_url).hostname or ""
        return frozenset({host.lower()})


def load_search_settings(environ: Mapping[str, str] | None = None) -> SearchSettings:
    """Build :class:`SearchSettings` from ``FATTY_SEARCH_``-prefixed variables."""

    source = os.environ if environ is None else environ
    data: dict[str, str] = {}
    for field in SearchSettings.model_fields:
        key = ENV_PREFIX + field.upper()
        if key in source:
            data[field] = source[key]
    return SearchSettings.model_validate(data)


class BraveResult(BaseModel):
    """A single Brave web result (untrusted; only ``url`` + ``title`` are used)."""

    model_config = ConfigDict(extra="ignore")

    url: str = ""
    title: str = ""

    @field_validator("title", mode="before")
    @classmethod
    def _truncate_title(cls, value: Any) -> Any:
        """Truncate (not reject) an overlong title.

        The title bound is a guard on untrusted provider content, not a contract the
        provider must honour: one overlong title truncates rather than failing the
        whole reply (which would map an otherwise-usable answer to
        :attr:`SearchStatus.FAILED`). Non-string values fall through to normal
        validation, which fails closed into the caller's status mapping.
        """

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
    ) -> dict[str, Any]: ...


def _default_transport(
    url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: float,
    allowed_hosts: frozenset[str],
    resolver: Resolver,
) -> dict[str, Any]:
    return get_json(
        url,
        headers=headers,
        timeout_seconds=timeout_seconds,
        allowed_hosts=allowed_hosts,
        resolver=resolver,
    )


@runtime_checkable
class SearchProvider(Protocol):
    """A pluggable search backend the official-source resolver queries.

    The adapter interface: a capability/availability surface plus a single
    :meth:`search` that maps a (caller-sanitized) item-identity query to candidate
    URLs and an explicit :class:`SearchStatus`.
    """

    @property
    def enabled(self) -> bool:
        """The self-host enable flag (a disabled provider is never queried)."""
        ...

    @property
    def available(self) -> bool:
        """Whether required credentials are present."""
        ...

    @property
    def capability(self) -> SearchCapability:
        """The static capability descriptor surfaced in diagnostics."""
        ...

    def search(self, query: str) -> SearchResult:
        """Return candidate result URLs + status for ``query`` (sanitized internally)."""
        ...


class BraveSearchProvider:
    """Hardened, allowlisted Brave Search adapter — the v1 default :class:`SearchProvider`.

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
        # Default to real DNS resolution when no resolver seam is injected.
        self._resolver = resolver or socket.getaddrinfo

    @property
    def enabled(self) -> bool:
        return self._settings.enabled

    @property
    def available(self) -> bool:
        return self._settings.is_available

    @property
    def capability(self) -> SearchCapability:
        return SearchCapability(
            id=OFFICIAL_SOURCE,
            source_type=OFFICIAL_SOURCE_TYPE,
            kinds=SEARCH_KINDS,
            enabled=self._settings.enabled,
            available=self._settings.is_available,
        )

    def search(self, query: str) -> SearchResult:
        """Search the provider for ``query`` and return candidate URLs + a status.

        Resolves to exactly one :class:`SearchStatus`. Returns no candidates for any
        non-:attr:`SearchStatus.SUCCESS` outcome. Only the sanitized item-identity
        query egresses; the key rides in a header. Transport/policy failures map to a
        status, never to a content-bearing exception.
        """

        if not self._settings.enabled:
            return SearchResult(status=SearchStatus.DISABLED)
        api_key = self._settings.api_key
        if api_key is None or not self._settings.is_available:
            return SearchResult(status=SearchStatus.UNAVAILABLE)

        sanitized = sanitize_query(query)
        if not sanitized:
            # Nothing to search; do not call the provider with an empty query.
            return SearchResult(status=SearchStatus.PARTIAL)

        # The key rides in the header, never the URL/query string, so it cannot leak
        # through a logged request line.
        headers = {_BRAVE_KEY_HEADER: api_key.get_secret_value()}
        try:
            raw = self._transport(
                self._settings.query_url(sanitized),
                headers=headers,
                timeout_seconds=self._settings.timeout_seconds,
                allowed_hosts=self._settings.allowed_hosts,
                resolver=self._resolver,
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
            candidates = _map_candidates(response, self._settings.max_results)
        except ValidationError:
            # A non-conforming / hostile body (the base URL is self-host-overridable,
            # so the payload is untrusted) maps to a status like any other failure —
            # never an uncaught exception whose repr would echo the provider input.
            return SearchResult(status=SearchStatus.FAILED)
        if not candidates:
            # The provider answered but offered no usable candidate URL.
            return SearchResult(status=SearchStatus.PARTIAL)
        return SearchResult(status=SearchStatus.SUCCESS, candidates=tuple(candidates))


def _map_candidates(response: BraveResponse, max_results: int) -> list[SearchCandidate]:
    """Map a Brave reply to fetchable candidate URLs, bounded by ``max_results``.

    Only public HTTP(S) URLs are eligible for the (separate) fetch step; anything
    else is dropped. The result list is never trusted as nutrition facts.
    """

    web = response.web
    if web is None:
        return []
    candidates: list[SearchCandidate] = []
    for result in web.results:
        url = result.url.strip()
        if urlsplit(url).scheme.lower() not in _FETCHABLE_SCHEMES:
            continue
        candidates.append(SearchCandidate(url=url, title=result.title))
        if len(candidates) >= max_results:
            break
    return candidates


def build_search_provider(settings: SearchSettings | None = None) -> SearchProvider:
    """Build the configured :class:`SearchProvider` from environment-loaded settings.

    The pluggable registry: the validated ``provider`` selects the backend. Only
    Brave is registered in v1; an unknown provider fails closed at config load.
    """

    resolved = settings or load_search_settings()
    if resolved.provider == BRAVE_PROVIDER:
        return BraveSearchProvider(resolved)
    # Unreachable: SearchSettings validates ``provider`` against KNOWN_PROVIDERS.
    raise ValueError(f"unsupported search provider: {resolved.provider}")
