"""Shared test fixtures.

Database-backed tests run against a throwaway, per-test SQLite database whose
schema is created by *running the Alembic migration* (not ``create_all``), so the
migration itself is exercised by the same tests that exercise the API.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine

from alembic import command
from app.db import create_db_engine
from app.main import create_app
from app.settings import Settings

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
def client(db_engine: Engine) -> Iterator[TestClient]:
    """A TestClient wired to the migrated SQLite database."""

    settings = Settings(environment="test", log_level="WARNING")
    app = create_app(settings=settings, engine=db_engine)
    with TestClient(app) as test_client:
        yield test_client
