"""Searched-result fetch egress policy for reference sources (FTY-166).

The **fetch half** of the ``reference_source`` evidence tier
(``docs/contracts/evidence-retrieval.md``): the SSRF / egress boundary for
retrieving a **public search-result page** (a nutrition reference page the search
adapter surfaced) and returning sanitized, active-content-stripped inert text for
downstream extraction. It ships no search adapter (that is FTY-079/164) and no
resolution pipeline of its own (FTY-166's resolver lives in ``official_step.py``);
it is the egress policy for searched public result URLs.

The policy difference from the official-source fetch (FTY-078) is deliberate and
explicit: a searched result URL points at an **arbitrary public host** the operator
could not have allowlisted in advance, so there is no pre-configured host
allowlist. Every other hardened-fetch protection is preserved unchanged — the
result URL is adversarial input (the search provider is untrusted), so the
boundary must hold even for attacker-chosen URLs:

- **HTTPS only.** A plain-HTTP, ``file:``, or other-scheme result URL is refused
  before a socket opens (no local-HTTP exception exists on this path).
- **Public IP only.** Every resolved address must be a public, globally-routable
  unicast IP; loopback, private, link-local (incl. the ``169.254.169.254``
  metadata service), CGNAT, multicast, reserved, and unspecified targets are
  refused, and the connection pins the vetted IP (no DNS-rebinding TOCTOU).
- **Redirects refused**, so a public result page cannot bounce the fetch inward.
- **Bounded timeout / size / content type** (inert text types only).
- **Active content stripped** — the returned body is inert text with every tag
  and attribute discarded.
- **Raw pages never persisted** — callers store extracted facts, the URL, a
  timestamp, and a content hash only (``docs/security/data-retention.md``).

Fail-closed switch: ``SLACKS_REFERENCE_FETCH_ENABLED=false`` refuses every fetch,
and the configured policy is surfaced (no URLs, no secrets) through
``GET /healthz/egress`` so an operator can see whether searched public result
fetch is on without reading code.
"""

from __future__ import annotations

import os
import socket
import urllib.parse
import urllib.request
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.estimator.hardened_fetch import (
    DEFAULT_MAX_TEXT_BYTES,
    DEFAULT_TEXT_CONTENT_TYPES,
    FetchPolicyError,
    Resolver,
    fetch_text,
)
from app.estimator.official_fetch import _parse_csv_lower

#: Reference-source fetch settings are read from variables with this prefix, e.g.
#: ``SLACKS_REFERENCE_FETCH_ENABLED``.
ENV_PREFIX = "SLACKS_REFERENCE_FETCH_"

#: The only scheme a searched public result page may use — no exceptions: the
#: local-HTTP carve-out (FTY-164) exists solely for the named local search service,
#: never for a result URL the (untrusted) search provider chose.
_ALLOWED_SCHEME = "https"


class ReferenceFetchSettings(BaseModel):
    """Validated searched-result fetch policy, read from ``SLACKS_REFERENCE_FETCH_`` vars.

    Frozen and ``extra="forbid"`` so the egress policy is immutable and unknown keys
    are rejected. Unlike the official-source fetch there is **no host allowlist**:
    the eligible targets are the public result URLs the search adapter returned,
    which cannot be enumerated ahead of time. The compensating control is the full
    hardened-fetch posture (HTTPS-only, public-IP-only, redirects refused, bounded,
    inert text) plus the explicit ``enabled`` off switch.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    #: Whether searched public result pages may be fetched at all. On by default —
    #: reference-source fallback is a default capability like search itself
    #: (FTY-164); set ``SLACKS_REFERENCE_FETCH_ENABLED=false`` to turn the tier off.
    enabled: bool = True
    #: Per-request wall-clock timeout. A documented tunable.
    timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    #: Response-size cap; a larger body fails closed.
    max_bytes: int = Field(default=DEFAULT_MAX_TEXT_BYTES, ge=1, le=10_000_000)
    #: Content types accepted from a result page; anything else fails closed.
    allowed_content_types: frozenset[str] = DEFAULT_TEXT_CONTENT_TYPES

    _normalize_content_types = field_validator("allowed_content_types", mode="before")(
        _parse_csv_lower
    )

    @property
    def is_available(self) -> bool:
        """Whether searched public result pages are fetchable (the enable flag)."""

        return self.enabled


def load_reference_fetch_settings(
    environ: Mapping[str, str] | None = None,
) -> ReferenceFetchSettings:
    """Build :class:`ReferenceFetchSettings` from ``SLACKS_REFERENCE_FETCH_`` variables."""

    source = os.environ if environ is None else environ
    data: dict[str, str] = {}
    for field in ReferenceFetchSettings.model_fields:
        key = ENV_PREFIX + field.upper()
        if key in source:
            data[field] = source[key]
    return ReferenceFetchSettings.model_validate(data)


def fetch_searched_result(
    url: str,
    settings: ReferenceFetchSettings,
    *,
    resolver: Resolver = socket.getaddrinfo,
    opener: urllib.request.OpenerDirector | None = None,
) -> str:
    """Fetch a public search-result ``url`` and return sanitized inert text.

    Applies the searched-result egress policy through the shared hardened fetch.
    The URL is untrusted (the search provider chose it), so the scheme is checked
    to be HTTPS *before* the host is admitted, the host is allowlisted **per
    result** (exactly the URL's own host — arbitrary public hosts are eligible,
    but the request can only go where the vetted URL points), and the full SSRF
    posture applies: public-IP-only with the vetted IP pinned, redirects refused,
    bounded timeout / size / content type, active content stripped. The returned
    body is inert text; the raw page is never persisted by any caller. Raises the
    hardened-fetch errors (:class:`~app.estimator.hardened_fetch.FetchPolicyError` /
    :class:`~app.estimator.hardened_fetch.FetchTransientError` /
    :class:`~app.estimator.hardened_fetch.FetchResponseError`); their messages are
    content-free.
    """

    if not settings.enabled:
        # Defense in depth: the resolver checks availability before searching, but
        # the fetch itself also fails closed when the tier is switched off.
        raise FetchPolicyError("reference_fetch_disabled")

    parts = urllib.parse.urlsplit(url)
    if parts.scheme.lower() != _ALLOWED_SCHEME:
        # Checked here as well as in the shared policy so a non-HTTPS result URL is
        # refused before its host could ever be treated as an allowed target.
        raise FetchPolicyError("scheme_not_allowed")
    host = (parts.hostname or "").lower()
    if not host:
        raise FetchPolicyError("host_not_allowed")

    return fetch_text(
        url,
        timeout_seconds=settings.timeout_seconds,
        allowed_hosts=frozenset({host}),
        allowed_content_types=settings.allowed_content_types,
        max_bytes=settings.max_bytes,
        resolver=resolver,
        opener=opener,
    )
