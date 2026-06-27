"""Health check route."""

from __future__ import annotations

from fastapi import APIRouter

from app.schemas.health import HealthStatus
from app.schemas.sources import SourcesStatus
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
