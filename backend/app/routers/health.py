"""Health check route."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.health import HealthStatus
from app.schemas.sources import EgressPolicy, SourcesStatus
from app.services import health as health_service
from app.services import sources as sources_service

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthStatus)
def healthz() -> HealthStatus:
    """Liveness probe: returns HTTP 200 with a typed status body."""

    return health_service.check_health()


@router.get("/healthz/sources", response_model=SourcesStatus)
def sources() -> SourcesStatus:
    """Config diagnostics: each evidence source's enabled/available capability.

    Surfaces provider availability (USDA FDC, Open Food Facts) per the
    evidence-retrieval contract, so a self-hoster can confirm which sources are on
    without trial calls. Carries no secrets and makes no external calls.
    """

    return sources_service.list_source_capabilities()


@router.get("/healthz/egress", response_model=EgressPolicy)
def egress() -> EgressPolicy:
    """Config diagnostics: the official-source fetch SSRF / egress policy (FTY-078).

    Surfaces the configured host allowlist and the bounded size/timeout/content-type
    limits (plus the fixed HTTPS-only, public-IP-only, no-redirect, active-content-
    stripping invariants), so a self-hoster can confirm the egress boundary without
    reading code. Carries no secrets and makes no external calls.
    """

    return sources_service.describe_egress_policy()
