"""Evidence-source diagnostics service (FTY-060).

Builds the source-provider capability descriptors surfaced in health/config
diagnostics (``docs/contracts/evidence-retrieval.md``) from the environment-loaded
provider settings. Reads config only — never the secret values — and makes no
external calls, so it is safe on a liveness-adjacent endpoint.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.estimator.fdc import FDC_SOURCE, FDC_SOURCE_TYPE, load_fdc_settings
from app.estimator.off import OFF_SOURCE, OFF_SOURCE_TYPE, load_off_settings
from app.estimator.official_fetch import load_official_fetch_settings
from app.estimator.search import (
    OFFICIAL_SOURCE,
    OFFICIAL_SOURCE_TYPE,
    SEARCH_KINDS,
    load_search_settings,
)
from app.schemas.sources import EgressPolicy, SourceCapability, SourcesStatus


def list_source_capabilities(environ: Mapping[str, str] | None = None) -> SourcesStatus:
    """Return the capability descriptor for each configured evidence source.

    The official-source search provider (FTY-079) is ``enabled`` by self-host flag but
    only ``available`` with an API key, so out of the box (no bundled key) it reports
    available=false; USDA FDC (generic foods) is always ``enabled`` but only
    ``available`` with an API key; Open Food Facts (barcode) needs no credentials, so
    it is always ``available`` and ``enabled`` unless a self-hoster turns it off.
    """

    search = load_search_settings(environ)
    off = load_off_settings(environ)
    fdc = load_fdc_settings(environ)

    return SourcesStatus(
        sources=[
            SourceCapability(
                id=OFFICIAL_SOURCE,
                source_type=OFFICIAL_SOURCE_TYPE,
                kinds=list(SEARCH_KINDS),
                enabled=search.enabled,
                available=search.is_available,
            ),
            SourceCapability(
                id=OFF_SOURCE,
                source_type=OFF_SOURCE_TYPE,
                kinds=["barcode"],
                enabled=off.enabled,
                available=off.is_available,
            ),
            SourceCapability(
                id=FDC_SOURCE,
                source_type=FDC_SOURCE_TYPE,
                kinds=["generic_food"],
                enabled=True,
                available=fdc.is_configured,
            ),
        ]
    )


def describe_egress_policy(environ: Mapping[str, str] | None = None) -> EgressPolicy:
    """Return the official-source fetch egress policy (FTY-078) for diagnostics.

    Surfaces the configured host allowlist and the page-fetch bounds (size, timeout,
    content types) plus the fixed hardened-fetch invariants, so a self-hoster can see
    the SSRF / egress boundary without reading code. Reads config only — never a
    secret — and makes no external calls, so it is safe on a liveness-adjacent endpoint.
    """

    official = load_official_fetch_settings(environ)
    return EgressPolicy(
        allowed_hosts=sorted(official.allowed_hosts),
        max_bytes=official.max_bytes,
        timeout_seconds=official.timeout_seconds,
        allowed_content_types=sorted(official.allowed_content_types),
    )
