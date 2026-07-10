"""FastAPI application factory.

``create_app`` validates settings, configures structured logging, and wires the
routers. Importing ``app`` builds the application from the process environment.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request, Response
from sqlalchemy.engine import Engine
from starlette.middleware.base import BaseHTTPMiddleware

from app.db import create_db_engine, create_session_factory
from app.estimator.enqueue import celery_enqueuer
from app.estimator.label_upload import synchronous_label_processor
from app.logging import configure_logging
from app.routers import (
    auth,
    corrections,
    daily_summary,
    food_suggestions,
    goals,
    health,
    log_events,
    profile,
    re_match,
    saved_foods,
    targets,
    weight_entries,
)
from app.security.rate_limit import build_redis_limiter
from app.settings import Settings, load_settings

logger = logging.getLogger(__name__)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add baseline security headers to every response.

    These headers are defense-in-depth controls (FTY-112):
    - ``X-Content-Type-Options: nosniff`` blocks MIME-confusion attacks.
    - ``X-Frame-Options: DENY`` blocks clickjacking (the API is never framed).
    - ``Referrer-Policy: no-referrer`` limits referrer leakage on redirects.

    HSTS and CSP are intentionally omitted: TLS termination is the reverse-proxy's
    concern, and a CSP is low-value for a JSON API consumed by a native client.
    """

    async def dispatch(self, request: Request, call_next: object) -> Response:
        response: Response = await call_next(request)  # type: ignore[operator]
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Settings are validated here (or passed in by tests); invalid environment
    configuration raises ``ValidationError`` before the app starts serving. The
    database engine is built from ``settings.database_url`` unless a pre-built
    one is supplied (tests inject a SQLite engine with the schema already
    migrated). The session factory is stored on ``app.state`` for the
    request-scoped ``get_session`` dependency.

    In ``production`` the interactive docs (``/docs``, ``/redoc``) and the raw
    OpenAPI schema (``/openapi.json``) are disabled so the full API surface is
    not publicly enumerable on a self-host. In ``development`` and ``test`` they
    remain available (current behaviour preserved).
    """

    settings = settings or load_settings()
    configure_logging(settings.log_level)

    # Gate interactive docs and OpenAPI schema off in production to reduce
    # reconnaissance exposure. Development and test keep them enabled.
    is_production = settings.environment == "production"
    app = FastAPI(
        title=settings.app_name,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.state.settings = settings
    db_engine = engine or create_db_engine(settings.database_url)
    app.state.db_engine = db_engine
    app.state.db_session_factory = create_session_factory(db_engine)
    # The estimation enqueuer is a swappable seam (FTY-040): production publishes
    # to Celery/Redis; tests inject a recording fake so creating an event needs
    # no live broker.
    app.state.estimation_enqueuer = celery_enqueuer
    # The label processor is a swappable seam (FTY-064): production resolves an
    # uploaded label image in-request through the real vision provider; tests
    # inject a double backed by a scripted provider so the upload endpoint needs
    # no live model.
    app.state.label_processor = synchronous_label_processor
    # The rate limiter is a swappable seam (FTY-118): production uses a
    # Redis-backed fixed-window counter shared across worker processes; tests
    # inject an in-memory double so the auth endpoint tests need no live Redis.
    # The seam can be replaced after create_app() returns (e.g. in conftest.py).
    app.state.rate_limiter = build_redis_limiter(settings.redis_url)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(profile.router)
    app.include_router(goals.router)
    app.include_router(log_events.router)
    app.include_router(corrections.router)
    app.include_router(re_match.router)
    app.include_router(saved_foods.router)
    app.include_router(food_suggestions.router)
    app.include_router(daily_summary.router)
    app.include_router(weight_entries.router)
    app.include_router(targets.router)

    # No secrets/personal data here: only the non-sensitive environment label.
    logger.info("backend application initialized", extra={"environment": settings.environment})
    return app


app = create_app()
