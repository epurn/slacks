"""Official-source fetch egress policy (FTY-078).

The **fetch half** of the ``official_source`` evidence tier
(``docs/contracts/food-resolution.md``): the configured SSRF / egress boundary for
retrieving an allowlisted public official-source page (restaurant, manufacturer, or
product page) and returning sanitized, active-content-stripped text for downstream
extraction. It ships no search adapter (FTY-079) and no resolution pipeline of its
own (FTY-062); it is the egress prerequisite for both.

Every fetch goes through FTY-044's :mod:`app.estimator.hardened_fetch`, so official
and USDA/OFF fetches share one audited egress boundary (HTTPS-only, public-IP-only,
host allowlist, redirects refused, bounded time/size/content-type, content-free
errors). This module adds only the **official-source configuration** — which hosts
are reachable and the page-fetch limits — read from ``SLACKS_OFFICIAL_FETCH_`` env
vars and surfaced (host allowlist + limits, no secrets) through
``GET /healthz/egress`` so an operator can see the egress policy without reading code.

Fail-closed by default: with no configured allowlist, **nothing** is fetchable.
"""

from __future__ import annotations

import os
import socket
import urllib.request
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.estimator.hardened_fetch import (
    DEFAULT_MAX_TEXT_BYTES,
    DEFAULT_TEXT_CONTENT_TYPES,
    Resolver,
    fetch_text,
)

#: Official-source fetch settings are read from variables with this prefix, e.g.
#: ``SLACKS_OFFICIAL_FETCH_ALLOWED_HOSTS``.
ENV_PREFIX = "SLACKS_OFFICIAL_FETCH_"


def _parse_csv_lower(value: Any) -> Any:
    """Parse a comma-separated env string into a lower-cased ``frozenset``.

    Blank entries are dropped so a trailing comma or stray whitespace cannot widen
    the allowlist. A non-string (already a collection) is passed through unchanged.
    """

    if isinstance(value, str):
        return frozenset(item.strip().lower() for item in value.split(",") if item.strip())
    return value


class OfficialFetchSettings(BaseModel):
    """Validated official-source fetch policy, read from ``SLACKS_OFFICIAL_FETCH_`` vars.

    Frozen and ``extra="forbid"`` so the egress policy is immutable and unknown keys
    are rejected. Fail-closed by default: an empty ``allowed_hosts`` means no page is
    fetchable. The hosts are the only targets the hardened fetch will contact (on top
    of its HTTPS-only, public-IP-only, redirect-refusing guarantees).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: The official-source hosts that may be fetched (lower-cased). **Empty → nothing
    #: is fetchable** (fail closed). Set ``SLACKS_OFFICIAL_FETCH_ALLOWED_HOSTS`` to a
    #: comma-separated host list to enable specific official sources.
    allowed_hosts: frozenset[str] = frozenset()
    #: Per-request wall-clock timeout. A documented tunable.
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    #: Response-size cap; a larger body fails closed.
    max_bytes: int = Field(default=DEFAULT_MAX_TEXT_BYTES, ge=1, le=10_000_000)
    #: Content types accepted from an official source; anything else fails closed.
    allowed_content_types: frozenset[str] = DEFAULT_TEXT_CONTENT_TYPES

    _normalize_hosts = field_validator("allowed_hosts", mode="before")(_parse_csv_lower)
    _normalize_content_types = field_validator("allowed_content_types", mode="before")(
        _parse_csv_lower
    )

    @property
    def is_available(self) -> bool:
        """Whether any official source is reachable (a non-empty allowlist)."""

        return bool(self.allowed_hosts)


def load_official_fetch_settings(
    environ: Mapping[str, str] | None = None,
) -> OfficialFetchSettings:
    """Build :class:`OfficialFetchSettings` from ``SLACKS_OFFICIAL_FETCH_`` variables."""

    source = os.environ if environ is None else environ
    data: dict[str, str] = {}
    for field in OfficialFetchSettings.model_fields:
        key = ENV_PREFIX + field.upper()
        if key in source:
            data[field] = source[key]
    return OfficialFetchSettings.model_validate(data)


def fetch_official_source(
    url: str,
    settings: OfficialFetchSettings,
    *,
    resolver: Resolver = socket.getaddrinfo,
    opener: urllib.request.OpenerDirector | None = None,
) -> str:
    """Fetch an allowlisted official-source ``url`` and return sanitized inert text.

    Applies the configured egress policy through the shared hardened fetch: HTTPS-only,
    the configured host allowlist, public-IP-only SSRF blocking, redirects refused, and
    the bounded timeout / size / content-type limits. The returned body is
    active-content-stripped inert text. Raises the hardened-fetch errors
    (:class:`~app.estimator.hardened_fetch.FetchPolicyError` /
    :class:`~app.estimator.hardened_fetch.FetchTransientError` /
    :class:`~app.estimator.hardened_fetch.FetchResponseError`); their messages are
    content-free.
    """

    return fetch_text(
        url,
        timeout_seconds=settings.timeout_seconds,
        allowed_hosts=settings.allowed_hosts,
        allowed_content_types=settings.allowed_content_types,
        max_bytes=settings.max_bytes,
        resolver=resolver,
        opener=opener,
    )
