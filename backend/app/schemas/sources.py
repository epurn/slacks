"""Evidence-source diagnostics boundary models (FTY-060).

The public shape of the source-provider capability descriptor surfaced in
health/config diagnostics, per ``docs/contracts/evidence-retrieval.md``: a
self-hoster (and later the mobile source-status UI) can see which evidence sources
are enabled and available without any trial calls. The descriptor carries **no**
secrets — only the source id, its hierarchy slot, the lookup kinds it serves, and
two booleans.
"""

from __future__ import annotations

from pydantic import BaseModel


class SourceCapability(BaseModel):
    """A single evidence source's static capability descriptor.

    Mirrors the **Provider Capability** contract: ``available`` reflects whether the
    required config/credentials are present; ``enabled`` reflects the self-host flag.
    A source is consulted only when both are true.
    """

    id: str
    source_type: str
    kinds: list[str]
    enabled: bool
    available: bool


class SourcesStatus(BaseModel):
    """Response body for ``GET /healthz/sources`` — all configured evidence sources."""

    sources: list[SourceCapability]


class SearchedResultFetchPolicy(BaseModel):
    """The searched-result (reference-source) fetch egress policy (FTY-166).

    Describes whether — and under what bounds — public search-result pages may be
    fetched for reference-source evidence. There is deliberately **no host
    allowlist**: eligible targets are the public result URLs the search adapter
    returned, so the surfaced policy is the enable switch, the bounds, and the fixed
    hardened-fetch invariants. Carries no secrets and never any URL from a user
    entry.
    """

    enabled: bool
    max_bytes: int
    timeout_seconds: float
    allowed_content_types: list[str]
    https_only: bool = True
    public_ip_only: bool = True
    redirects_followed: bool = False
    active_content_stripped: bool = True
    raw_pages_persisted: bool = False


class EgressPolicy(BaseModel):
    """The evidence-fetch egress policy (FTY-078/166), for operator diagnostics.

    The configured SSRF / egress boundary surfaced at ``GET /healthz/egress`` so a
    self-hoster can confirm the policy without reading code. Carries **no** secrets —
    only the non-secret host allowlist and the (non-secret) bound values. The boolean
    invariants (``https_only`` / ``public_ip_only`` / ``redirects_followed``) are fixed
    properties of the hardened fetch, restated here so the egress contract is visible.
    ``searched_result_fetch`` describes the reference-source tier: whether searched
    public result pages may be fetched at all (FTY-166).
    """

    allowed_hosts: list[str]
    max_bytes: int
    timeout_seconds: float
    allowed_content_types: list[str]
    https_only: bool = True
    public_ip_only: bool = True
    redirects_followed: bool = False
    active_content_stripped: bool = True
    searched_result_fetch: SearchedResultFetchPolicy
