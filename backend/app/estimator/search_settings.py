"""Validated official-source search provider settings."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any, Final
from urllib.parse import urlencode, urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.estimator.search_sanitization import is_local_search_host

#: Search settings are read from variables with this prefix, e.g.
#: ``SLACKS_SEARCH_API_KEY``.
ENV_PREFIX = "SLACKS_SEARCH_"

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


class SearchSettings(BaseModel):
    """Validated search-provider config, read from ``SLACKS_SEARCH_`` env vars.

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
            raise ValueError(f"SLACKS_SEARCH_PROVIDER must be one of {sorted(KNOWN_PROVIDERS)}")
        if self.provider == NONE_PROVIDER:
            return self  # no egress, nothing to validate
        lowered = self.base_url.lower()
        if lowered.startswith("https://"):
            return self
        if (
            self.provider == SEARXNG_PROVIDER
            and lowered.startswith("http://")
            and is_local_search_host(urlsplit(self.base_url).hostname or "")
        ):
            return self
        if self.provider == SEARXNG_PROVIDER:
            raise ValueError(
                "SLACKS_SEARCH_BASE_URL must be https, or http for the local SearXNG "
                "service only (searxng / localhost / loopback)"
            )
        raise ValueError("SLACKS_SEARCH_BASE_URL must be an https URL")

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
    """Build :class:`SearchSettings` from ``SLACKS_SEARCH_``-prefixed variables."""

    source = os.environ if environ is None else environ
    data: dict[str, str] = {}
    for field in SearchSettings.model_fields:
        key = ENV_PREFIX + field.upper()
        if key in source:
            data[field] = source[key]
    return SearchSettings.model_validate(data)
