"""FastAPI application factory.

``create_app`` validates settings, configures structured logging, and wires the
routers. Importing ``app`` builds the application from the process environment.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from sqlalchemy.engine import Engine

from app.db import create_db_engine, create_session_factory
from app.logging import configure_logging
from app.routers import auth, health, profile
from app.settings import Settings, load_settings

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Settings are validated here (or passed in by tests); invalid environment
    configuration raises ``ValidationError`` before the app starts serving. The
    database engine is built from ``settings.database_url`` unless a pre-built
    one is supplied (tests inject a SQLite engine with the schema already
    migrated). The session factory is stored on ``app.state`` for the
    request-scoped ``get_session`` dependency.
    """

    settings = settings or load_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title=settings.app_name)
    app.state.settings = settings
    db_engine = engine or create_db_engine(settings.database_url)
    app.state.db_engine = db_engine
    app.state.db_session_factory = create_session_factory(db_engine)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(profile.router)

    # No secrets/personal data here: only the non-sensitive environment label.
    logger.info("backend application initialized", extra={"environment": settings.environment})
    return app


app = create_app()
