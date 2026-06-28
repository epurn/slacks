"""Health service.

Routes delegate here from the outset so the route layer stays a thin HTTP
boundary. Real readiness checks (database, queue) live here; liveness
(check_health) stays a static process-up check.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.schemas.health import HealthStatus, ReadinessStatus


def check_health() -> HealthStatus:
    """Return the current service health status (liveness — never touches the DB)."""

    return HealthStatus(status="ok")


def check_readiness(session: Session) -> ReadinessStatus:
    """Probe DB reachability via a cheap SELECT 1.

    Raises on any DB failure; the caller (handler) converts that to a 503.
    """

    session.execute(text("SELECT 1"))
    return ReadinessStatus(status="ready")
