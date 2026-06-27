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
from app.schemas.sources import SourceCapability, SourcesStatus


def list_source_capabilities(environ: Mapping[str, str] | None = None) -> SourcesStatus:
    """Return the capability descriptor for each configured evidence source.

    USDA FDC (generic foods) is always ``enabled`` but only ``available`` with an API
    key; Open Food Facts (barcode) needs no credentials, so it is always ``available``
    and ``enabled`` unless a self-hoster turns it off.
    """

    fdc = load_fdc_settings(environ)
    off = load_off_settings(environ)

    return SourcesStatus(
        sources=[
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
