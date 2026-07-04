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
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import DateTime, create_engine
from sqlalchemy.engine import Dialect, Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator


class Base(DeclarativeBase):
    """Declarative base for all ORM models; carries the schema metadata."""


class UtcDateTime(TypeDecorator[datetime]):
    """A ``timestamptz`` column that always stores and returns UTC-aware datetimes.

    SQLAlchemy's ``DateTime(timezone=True)`` only preserves the offset on backends
    that support it (Postgres). SQLite has no native timezone type: it discards the
    offset on write and hands values back **naive** on read. A naive datetime then
    serializes in a DTO *without* a UTC offset, so a client reads the instant as its
    own local time — the ambiguity that lets an entry logged the previous evening
    render under "Today" (audit finding A6). Storing UTC end-to-end is worthless if
    the wire value is naive.

    This decorator closes the gap uniformly, independent of backend:

    - **on write** the value is normalized to UTC before it is stored (a naive value
      is assumed to be UTC — matching the app's ``datetime.now(UTC)`` write
      convention — and an offset-aware value is converted), so no naive or local
      instant is ever persisted;
    - **on read** the value is returned tz-aware in UTC — the offset is re-attached
      on backends (SQLite) that dropped it, and normalized on those that kept it — so
      every read path and DTO sees an unambiguous instant that serializes with an
      explicit ``+00:00`` offset.

    The underlying DDL is unchanged (``TIMESTAMP WITH TIME ZONE`` on Postgres,
    the same text storage on SQLite), so swapping ``DateTime(timezone=True)`` for
    this type requires **no migration**.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, _dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, _dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


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
