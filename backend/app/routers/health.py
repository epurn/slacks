"""Health check routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.health import HealthStatus, ReadinessStatus
from app.schemas.sources import EgressPolicy, SourcesStatus
from app.services import health as health_service
from app.services import sources as sources_service

router = APIRouter(tags=["health"])


@router.get("/healthz", response_model=HealthStatus)
def healthz() -> HealthStatus:
    """Liveness probe: returns HTTP 200 with a typed status body."""

    return health_service.check_health()


@router.get("/readyz", response_model=ReadinessStatus)
def readyz(session: Annotated[Session, Depends(get_session)]) -> ReadinessStatus:
    """Readiness probe: returns HTTP 200 when the database is reachable.

    Runs a cheap SELECT 1 against the request-scoped DB session. Returns
    503 Service Unavailable on any DB failure; the body carries no internal
    detail (no stack trace, driver message, DSN, or host).
    """

    try:
        return health_service.check_readiness(session)
    except Exception:
        # Raise from None so the internal DB error is not chained into the response.
        raise HTTPException(status_code=503, detail="not ready") from None


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
