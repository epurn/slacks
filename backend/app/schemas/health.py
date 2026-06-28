"""Health endpoint boundary models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthStatus(BaseModel):
    """Response body for ``GET /healthz``.

    The shape (``{"status": "ok"}``) and path are a contract relied on by infra
    healthchecks (FTY-011) and later stories; changes here are contract changes.
    """

    status: Literal["ok"] = "ok"


class ReadinessStatus(BaseModel):
    """Response body for ``GET /readyz``.

    Reports DB reachability: ``{"status": "ready"}`` when the database answers
    a ``SELECT 1`` probe. A DB-down path returns a generic ``503`` with no
    internal detail; this body is only returned on the ``200`` path.
    """

    status: Literal["ready"] = "ready"
