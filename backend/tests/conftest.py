"""Shared test fixtures.

Database-backed tests run against a throwaway, per-test SQLite database whose
schema is created by *running the Alembic migration* (not ``create_all``), so the
migration itself is exercised by the same tests that exercise the API.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from alembic import command
from app.db import create_db_engine
from app.main import create_app
from app.security.rate_limit import InMemoryRateLimiter
from app.settings import Settings

#: Env var holding a Postgres URL for the opt-in, Postgres-exercised migration
#: guard (FTY-143). When set, the Postgres migration test runs against it; when
#: unset, that test skips so a fresh checkout and the SQLite-only path stay green
#: without a running Postgres. CI wires this against a real Postgres in FTY-144.
POSTGRES_TEST_URL_ENV = "FATTY_TEST_DATABASE_URL"


class RecordingEnqueuer:
    """Test double for the estimation enqueuer (FTY-040).

    Records each enqueue call instead of publishing to Celery/Redis, so API tests
    that create log events never need a live broker and can assert exactly one
    job was enqueued with the right ids.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[uuid.UUID, uuid.UUID]] = []

    def __call__(self, *, log_event_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self.calls.append((log_event_id, user_id))


#: Repository path to the backend package root (where ``alembic.ini`` lives).
BACKEND_ROOT = Path(__file__).resolve().parents[1]


def alembic_config() -> Config:
    """Build an Alembic ``Config`` pointing at the backend's ``alembic.ini``."""

    return Config(str(BACKEND_ROOT / "alembic.ini"))


def upgrade(engine: Engine, revision: str = "head") -> None:
    """Run ``alembic upgrade`` to ``revision`` against ``engine``'s connection."""

    cfg = alembic_config()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.upgrade(cfg, revision)


def downgrade(engine: Engine, revision: str = "base") -> None:
    """Run ``alembic downgrade`` to ``revision`` against ``engine``'s connection."""

    cfg = alembic_config()
    with engine.begin() as connection:
        cfg.attributes["connection"] = connection
        command.downgrade(cfg, revision)


@pytest.fixture
def db_engine(tmp_path: Path) -> Iterator[Engine]:
    """A file-backed SQLite engine with the baseline migration applied."""

    engine = create_db_engine(f"sqlite:///{tmp_path / 'test.db'}")
    upgrade(engine)
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def pg_engine() -> Iterator[Engine]:
    """A Postgres engine for the opt-in migration guard (FTY-143).

    Built from ``FATTY_TEST_DATABASE_URL`` via the production ``create_db_engine``
    (so the test exercises the same driver/URL handling the deploy uses). Skips
    the requesting test when the env var is unset, keeping the SQLite-only path
    green without a running Postgres.

    Unlike the SQLite engines, a Postgres database persists across runs, so the
    fixture brackets the test with ``downgrade base`` on both setup and teardown:
    setup clears any schema a previous (possibly failed) run left behind, and
    teardown leaves the database empty for the next run. No application or user
    data is involved — the migrations operate on a synthetic schema only.
    """

    url = os.environ.get(POSTGRES_TEST_URL_ENV)
    if not url:
        pytest.skip(f"{POSTGRES_TEST_URL_ENV} not set; skipping Postgres migration guard")

    engine = create_db_engine(url)
    try:
        downgrade(engine, "base")
        yield engine
        downgrade(engine, "base")
    finally:
        engine.dispose()


@pytest.fixture
def enqueuer() -> RecordingEnqueuer:
    """A recording estimation enqueuer installed on the test app."""

    return RecordingEnqueuer()


@pytest.fixture
def rate_limiter() -> InMemoryRateLimiter:
    """A fresh in-memory rate limiter installed on the test app (FTY-118).

    Tests that need to control or inspect rate-limit state can request this
    fixture directly alongside ``client``.
    """

    return InMemoryRateLimiter()


@pytest.fixture
def client(
    db_engine: Engine, enqueuer: RecordingEnqueuer, rate_limiter: InMemoryRateLimiter
) -> Iterator[TestClient]:
    """A TestClient wired to the migrated SQLite database.

    The estimation enqueuer is replaced with the recording double so creating a
    log event does not reach a live broker; tests requesting the ``enqueuer``
    fixture see the same instance.

    The rate limiter is replaced with an in-memory double so auth endpoint tests
    need no live Redis; tests requesting ``rate_limiter`` see the same instance.
    """

    settings = Settings(environment="test", log_level="WARNING")
    app = create_app(settings=settings, engine=db_engine)
    app.state.estimation_enqueuer = enqueuer
    app.state.rate_limiter = rate_limiter
    with TestClient(app) as test_client:
        yield test_client
