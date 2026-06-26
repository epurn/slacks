"""Alembic migration environment.

The target metadata is :data:`app.db.Base.metadata`, populated by importing the
models. The database URL is resolved from application settings so migrations and
the app share one source of truth and no credentials are committed.

Two entry paths are supported:

- CLI (``alembic upgrade head``): an engine is built from the resolved URL.
- Programmatic (tests): a live SQLAlchemy connection passed via
  ``config.attributes["connection"]`` is reused, so the migration apply/rollback
  test can run against a throwaway SQLite database.
"""

from __future__ import annotations

from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

from alembic import context

# Importing the models registers every table on Base.metadata for autogenerate.
from app.db import Base
from app.models import estimation as _estimation  # noqa: F401  (import for side effects)
from app.models import identity as _identity  # noqa: F401  (import for side effects)
from app.models import log_events as _log_events  # noqa: F401  (import for side effects)
from app.models import targets as _targets  # noqa: F401  (import for side effects)
from app.settings import load_settings

config = context.config

target_metadata = Base.metadata


def _resolve_url() -> str:
    """Resolve the migration target URL from settings (``FATTY_DATABASE_URL``)."""

    return load_settings().database_url


def _run(connection: Connection) -> None:
    """Configure the context for ``connection`` and run the migrations.

    ``render_as_batch`` is enabled for SQLite so future ALTER-heavy migrations
    work on a dialect without native ALTER support; the baseline only creates
    tables, so it is harmless here.
    """

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode, emitting SQL against a URL."""

    context.configure(
        url=_resolve_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live connection."""

    connection = config.attributes.get("connection", None)
    if connection is not None:
        _run(connection)
        return

    config.set_main_option("sqlalchemy.url", _resolve_url())
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as conn:
        _run(conn)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
