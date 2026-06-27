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
