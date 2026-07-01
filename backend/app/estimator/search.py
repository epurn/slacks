"""Pluggable official-source search-provider adapter (FTY-079, FTY-164).

This is the **search half** of the ``official_source`` tier in the
evidence-retrieval source hierarchy (``docs/contracts/evidence-retrieval.md``). It
takes a **sanitized item-identity query** (product / restaurant / manufacturer
name) and returns a bounded list of candidate result URLs plus an explicit lookup
**status**, sending **no personal context** to the provider. It ships no fetcher
and no resolution pipeline of its own: the hardened fetcher for the result URLs is
FTY-078, and the official-source resolution step that consumes the candidates is
FTY-062. This adapter is the search-boundary prerequisite for both.

Design, mirroring the FDC / OFF evidence adapters:

- **Pluggable.** :class:`SearchProvider` is the adapter interface, selected by
  ``FATTY_SEARCH_PROVIDER``. Three backends are registered: **SearXNG** (the
  keyless default, FTY-164), **Brave Search** (explicit opt-in, needs an API
  key), and **``none``** (an explicit operator off switch).
- **Keyless and on by default (FTY-164).** The default backend is a local /
  self-hosted SearXNG instance (``http://searxng:8080`` in the dev stack), which
  needs no API key — so a normal dev/self-host install starts with search
  **available**, and callers (FTY-062) only fall through to the
  model-prior-with-status path when the instance is genuinely unreachable.
  ``FATTY_SEARCH_ENABLED=false`` or ``FATTY_SEARCH_PROVIDER=none`` turns search
  off explicitly (:attr:`SearchStatus.DISABLED`); selecting ``brave`` without a
  key reports :attr:`SearchStatus.UNAVAILABLE` exactly as before.
- **Narrow local-HTTP exception.** Base URLs must be ``https``, with one narrow
  carve-out: the SearXNG backend may use plain ``http`` **only** for the local
  service names the dev stack needs (``searxng``, ``localhost``, loopback
  literals), enforced both at config validation and again at egress by the
  hardened fetcher's inverted local-address posture. A public SearXNG endpoint
  must be HTTPS; Brave is HTTPS-only, no exception.
- **Status surface.** Every lookup resolves to exactly one
  :class:`SearchStatus`, aligned with the FTY-045 evidence-retrieval status
  vocabulary (``disabled`` / ``unavailable`` / ``rate_limited`` / ``failed`` /
  ``partial`` / ``success``), and the capability/availability signal is reflected
  in ``GET /healthz/sources`` diagnostics.
- **Query sanitization / data minimization.** :func:`sanitize_query` is the single
  chokepoint every query passes through before egress: control characters are
  stripped, whitespace collapsed, and the string length-bounded. Each adapter's
  request shape is closed — ``q`` + ``count`` for Brave, ``q`` + ``format=json``
  for SearXNG — so there is no channel for profile, weight, food history, or
  event metadata to reach the provider.
- **Secret handling.** The Brave API key is a :class:`~pydantic.SecretStr` read
  from the environment only, never exposed to clients, never logged, and carried
  in the ``X-Subscription-Token`` **header** (never the query string), so it
  cannot leak through a logged URL. SearXNG has no key at all.
- **Content-free errors.** Transport failures are mapped to a status, never to an
  exception that echoes the query, key, headers, or response body.
"""

from __future__ import annotations

import ipaddress
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

#: The keyless local/self-hosted SearXNG backend — the default (FTY-164).
SEARXNG_PROVIDER = "searxng"

#: The Brave Search backend — explicit opt-in, requires an API key.
BRAVE_PROVIDER = "brave"

#: The explicit operator off switch: search is disabled, no backend is queried.
NONE_PROVIDER = "none"

#: Known, registered search backends. Adding a provider means registering its key
#: here and a :class:`SearchProvider` adapter for it.
KNOWN_PROVIDERS: Final[frozenset[str]] = frozenset(
    {SEARXNG_PROVIDER, BRAVE_PROVIDER, NONE_PROVIDER}
)

#: Default SearXNG base — the dev-stack service target (FTY-165 runs the container).
DEFAULT_SEARXNG_BASE_URL = "http://searxng:8080"

#: SearXNG's search path appended to the base URL (``?q=...&format=json``).
_SEARXNG_SEARCH_PATH = "/search"

#: Default Brave Search API base. Overridable for self-host proxies/mirrors via env.
DEFAULT_BRAVE_BASE_URL = "https://api.search.brave.com"

#: Brave's web-search path appended to the base URL.
_BRAVE_SEARCH_PATH = "/res/v1/web/search"

#: Brave carries the subscription key in this request header (never the query
#: string), so it cannot leak through a logged URL.
_BRAVE_KEY_HEADER = "X-Subscription-Token"

#: The only host **names** the SearXNG backend may reach over plain HTTP: the
#: dev-stack service name and localhost. Loopback IP literals are matched by
#: :func:`_is_local_search_host`; everything else must be HTTPS.
LOCAL_SEARXNG_HTTP_HOSTS: Final[frozenset[str]] = frozenset({"searxng", "localhost"})

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


def _is_local_search_host(host: str) -> bool:
    """Return whether ``host`` is a local service name eligible for plain HTTP.

    The narrow FTY-164 rule: exactly the dev-stack service names
    (:data:`LOCAL_SEARXNG_HTTP_HOSTS`) plus loopback IP literals. Any other host —
    including private-range IPs and internal DNS names — must use HTTPS.
    """

    lowered = host.lower()
    if lowered in LOCAL_SEARXNG_HTTP_HOSTS:
        return True
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        return False


class SearchSettings(BaseModel):
    """Validated search-provider config, read from ``FATTY_SEARCH_`` env vars.

    Frozen and ``extra="forbid"`` so config is immutable and unknown keys are
    rejected. The default backend is the keyless local SearXNG instance, so search
    is enabled **and available** out of the box with no API key (FTY-164). The base
    URL must be ``https``, except that SearXNG may use plain ``http`` for the local
    dev-stack targets only (``searxng`` / ``localhost`` / loopback); the host is
    derived from it for the request allowlist.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Which registered backend to use: ``searxng`` (keyless default), ``brave``
    #: (opt-in, keyed), or ``none`` (explicit operator off switch).
    provider: str = SEARXNG_PROVIDER
    #: Self-host enable/disable flag. On by default; set ``false`` (or select the
    #: ``none`` provider) to turn the source off explicitly.
    enabled: bool = True
    #: Brave API key (secret). Required only by the ``brave`` backend — absent →
    #: Brave is unavailable. Read from env only; never logged or sent to clients.
    #: SearXNG ignores it entirely.
    api_key: SecretStr | None = None
    #: Provider API base. Defaults per provider (SearXNG → the dev-stack service,
    #: Brave → the public API) when not set explicitly.
    base_url: str = ""
    #: Per-request wall-clock timeout. A documented tunable.
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    #: Number of candidate result URLs requested / surfaced.
    max_results: int = Field(default=5, ge=1, le=20)

    @model_validator(mode="before")
    @classmethod
    def _default_base_url(cls, data: Any) -> Any:
        """Fill the per-provider default base URL when none is configured."""

        if isinstance(data, dict) and not data.get("base_url"):
            provider = data.get("provider", SEARXNG_PROVIDER)
            defaults = {
                SEARXNG_PROVIDER: DEFAULT_SEARXNG_BASE_URL,
                BRAVE_PROVIDER: DEFAULT_BRAVE_BASE_URL,
                # ``none`` never egresses; the value is inert but keeps the shape valid.
                NONE_PROVIDER: DEFAULT_SEARXNG_BASE_URL,
            }
            if provider in defaults:
                data = {**data, "base_url": defaults[provider]}
        return data

    @model_validator(mode="after")
    def _validate(self) -> SearchSettings:
        """Fail closed on an unknown provider or a base URL outside the scheme rules.

        Brave is HTTPS-only. SearXNG is HTTPS, with plain HTTP admitted **only** for
        the local dev-stack targets (``searxng`` / ``localhost`` / loopback) — a
        public or otherwise non-local ``http`` SearXNG URL is rejected here, and the
        hardened fetcher re-checks the resolved addresses at egress.
        """

        if self.provider not in KNOWN_PROVIDERS:
            raise ValueError(f"FATTY_SEARCH_PROVIDER must be one of {sorted(KNOWN_PROVIDERS)}")
        if self.provider == NONE_PROVIDER:
            return self  # no egress, nothing to validate
        lowered = self.base_url.lower()
        if lowered.startswith("https://"):
            return self
        if (
            self.provider == SEARXNG_PROVIDER
            and lowered.startswith("http://")
            and _is_local_search_host(urlsplit(self.base_url).hostname or "")
        ):
            return self
        if self.provider == SEARXNG_PROVIDER:
            raise ValueError(
                "FATTY_SEARCH_BASE_URL must be https, or http for the local SearXNG "
                "service only (searxng / localhost / loopback)"
            )
        raise ValueError("FATTY_SEARCH_BASE_URL must be an https URL")

    @property
    def is_enabled(self) -> bool:
        """Whether search is on: the flag is set and the provider is not ``none``."""

        return self.enabled and self.provider != NONE_PROVIDER

    @property
    def is_available(self) -> bool:
        """Whether the backend's required credentials are present.

        SearXNG needs none, so it is always available; Brave requires the API key;
        ``none`` is never available (search is explicitly off).
        """

        if self.provider == SEARXNG_PROVIDER:
            return True
        if self.provider == BRAVE_PROVIDER:
            return self.api_key is not None and bool(self.api_key.get_secret_value())
        return False

    @property
    def search_url(self) -> str:
        """The provider's web-search endpoint for the configured base URL."""

        path = _SEARXNG_SEARCH_PATH if self.provider == SEARXNG_PROVIDER else _BRAVE_SEARCH_PATH
        return f"{self.base_url.rstrip('/')}{path}"

    def query_url(self, sanitized_query: str) -> str:
        """The full search URL for ``sanitized_query`` (no secret ever rides in it).

        The request shape is closed per backend: Brave carries ``q`` (the sanitized
        item identity) + ``count`` (its key travels in the request header); SearXNG
        carries ``q`` + ``format=json`` (the result bound is applied client-side —
        the SearXNG API has no count parameter).
        """

        if self.provider == SEARXNG_PROVIDER:
            params = urlencode({"q": sanitized_query, "format": "json"})
        else:
            params = urlencode({"q": sanitized_query, "count": self.max_results})
        return f"{self.search_url}?{params}"

    @property
    def allowed_hosts(self) -> frozenset[str]:
        """The single allowlisted host (derived from the base URL) for fetches."""

        host = urlsplit(self.base_url).hostname or ""
        return frozenset({host.lower()})

    @property
    def local_http_hosts(self) -> frozenset[str]:
        """The host granted the narrow local-HTTP exception, if the base URL uses it.

        Non-empty only for a SearXNG base URL that validated as local plain HTTP;
        every other configuration gets the standard HTTPS-only egress policy.
        """

        parts = urlsplit(self.base_url)
        if self.provider == SEARXNG_PROVIDER and parts.scheme.lower() == "http":
            return frozenset({(parts.hostname or "").lower()})
        return frozenset()


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
        # Default to real DNS resolution when no resolver seam is injected.
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
        """Search the provider for ``query`` and return candidate URLs + a status.

        Resolves to exactly one :class:`SearchStatus`. Returns no candidates for any
        non-:attr:`SearchStatus.SUCCESS` outcome. Only the sanitized item-identity
        query egresses; the key rides in a header. Transport/policy failures map to a
        status, never to a content-bearing exception.
        """

        if not self._settings.is_enabled:
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
                # Brave is HTTPS-only: no local-HTTP exception, ever.
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
            # A non-conforming / hostile body (the base URL is self-host-overridable,
            # so the payload is untrusted) maps to a status like any other failure —
            # never an uncaught exception whose repr would echo the provider input.
            return SearchResult(status=SearchStatus.FAILED)
        if not candidates:
            # The provider answered but offered no usable candidate URL.
            return SearchResult(status=SearchStatus.PARTIAL)
        return SearchResult(status=SearchStatus.SUCCESS, candidates=tuple(candidates))


class SearXNGSearchProvider:
    """Hardened, allowlisted SearXNG adapter — the keyless default :class:`SearchProvider`.

    Queries a local/self-hosted SearXNG instance's JSON API
    (``/search?q=...&format=json``) with **no credential at all**: the request
    carries only the sanitized item-identity query and ``format=json``. Egress goes
    through the hardened fetcher; a local plain-HTTP base URL rides the narrow
    ``local_http_hosts`` exception (loopback/private targets only), any other base
    URL gets the standard HTTPS-only policy. The ``transport`` and ``resolver``
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
        """Search the instance for ``query`` and return candidate URLs + a status.

        Same contract as the Brave adapter: exactly one :class:`SearchStatus`, no
        candidates on a non-success outcome, only the sanitized item identity
        egresses, and transport/policy failures map to a status — never to a
        content-bearing exception.
        """

        if not self._settings.is_enabled:
            return SearchResult(status=SearchStatus.DISABLED)

        sanitized = sanitize_query(query)
        if not sanitized:
            # Nothing to search; do not call the provider with an empty query.
            return SearchResult(status=SearchStatus.PARTIAL)

        try:
            raw = self._transport(
                self._settings.query_url(sanitized),
                # Keyless by design: no credential header exists to send.
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
            # Untrusted body (a self-hosted instance can be misconfigured or hostile):
            # a non-conforming reply maps to a status, never an echoing exception.
            return SearchResult(status=SearchStatus.FAILED)
        if not candidates:
            # The instance answered but offered no usable candidate URL.
            return SearchResult(status=SearchStatus.PARTIAL)
        return SearchResult(status=SearchStatus.SUCCESS, candidates=tuple(candidates))


class NullSearchProvider:
    """The ``none`` backend: search explicitly turned off by the operator.

    Never egresses anything; every lookup is :attr:`SearchStatus.DISABLED` and the
    capability descriptor reports enabled/available false, so diagnostics show the
    deliberate opt-out rather than a missing credential.
    """

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
    """Map provider results to fetchable candidate URLs, bounded by ``max_results``.

    Shared by both backends. Only public HTTP(S) URLs are eligible for the
    (separate) fetch step; anything else is dropped. The result list is never
    trusted as nutrition facts.
    """

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
    """Build the configured :class:`SearchProvider` from environment-loaded settings.

    The pluggable registry: the validated ``provider`` selects the backend —
    ``searxng`` (the keyless default), ``brave`` (opt-in, keyed), or ``none`` (the
    explicit off switch). An unknown provider fails closed at config load.
    """

    resolved = settings or load_search_settings()
    if resolved.provider == SEARXNG_PROVIDER:
        return SearXNGSearchProvider(resolved)
    if resolved.provider == BRAVE_PROVIDER:
        return BraveSearchProvider(resolved)
    if resolved.provider == NONE_PROVIDER:
        return NullSearchProvider(resolved)
    # Unreachable: SearchSettings validates ``provider`` against KNOWN_PROVIDERS.
    raise ValueError(f"unsupported search provider: {resolved.provider}")
