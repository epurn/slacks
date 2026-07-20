"""Migration apply/rollback test for the log-event ``name`` label (FTY-421).

Proves the acceptance criteria: the 0023 migration applies cleanly on top of 0022
and is fully reversible, the ``name`` column is nullable, and the prior
``log_events`` schema is intact after rollback. Runs against a throwaway SQLite
database (the FTY-143 Postgres guard exercises the full chain on Postgres).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from app.db import create_db_engine
from tests.conftest import downgrade, upgrade


def test_name_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'name.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)

        column = next(c for c in inspector.get_columns("log_events") if c["name"] == "name")
        assert column["nullable"] is True

        # Roll back only the 0023 migration; the column must be gone and the prior
        # log_events schema intact.
        downgrade(engine, "0022")
        after = inspect(engine)
        assert "name" not in {c["name"] for c in after.get_columns("log_events")}
        assert {
            "id",
            "user_id",
            "raw_text",
            "status",
            "idempotency_key",
            "voided_at",
            "created_at",
            "updated_at",
        } <= {c["name"] for c in after.get_columns("log_events")}
    finally:
        engine.dispose()
