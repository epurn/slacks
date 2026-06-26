"""Database engine, session factory, and the request-scoped session dependency.

Persistence is explicit and migration-backed (see ``alembic/``): the ORM models
in :mod:`app.models` define the schema, and Alembic owns the versioned migrations
that create it. The application never calls ``create_all`` in production; the
schema is applied by running migrations.

The engine is built from :class:`app.settings.Settings.database_url`. SQLite URLs
are supported so tests (and the migration apply/rollback test) can run against a
throwaway database without a live Postgres; the Postgres driver is used at
runtime in the Docker Compose / self-host stack.
"""

from __future__ import annotations

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    """Declarative base for all ORM models; carries the schema metadata."""


def create_db_engine(database_url: str) -> Engine:
    """Build a SQLAlchemy :class:`~sqlalchemy.engine.Engine` for ``database_url``.

    SQLite needs ``check_same_thread=False`` because the FastAPI test client uses
    a session across threads. All other dialects (Postgres at runtime) use the
    driver defaults.
    """

    url = _normalize_url(database_url)
    connect_args: dict[str, object] = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    # pool_pre_ping avoids handing out connections the database has already
    # dropped (common with long-lived self-host deployments).
    return create_engine(url, pool_pre_ping=True, connect_args=connect_args)


def _normalize_url(database_url: str) -> str:
    """Select the installed psycopg (v3) driver for bare ``postgresql://`` URLs.

    The infra env contract (FTY-011) supplies a plain ``postgresql://`` URL.
    SQLAlchemy would otherwise default that to the psycopg2 dialect, which is not
    installed; rewriting the scheme keeps the env contract stable while binding
    to the psycopg3 driver this project depends on.
    """

    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg://" + database_url[len("postgresql://") :]
    return database_url


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a configured :class:`~sqlalchemy.orm.sessionmaker` bound to ``engine``."""

    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    """FastAPI dependency yielding a request-scoped :class:`~sqlalchemy.orm.Session`.

    The session factory is created once at app startup and stored on
    ``app.state``; tests override it with a SQLite-backed factory. The session is
    always closed, and rolled back if the handler raised, so a failed request
    never leaks a partially-committed transaction.
    """

    factory: sessionmaker[Session] = request.app.state.db_session_factory
    session = factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
