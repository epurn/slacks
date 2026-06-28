"""Migration apply/rollback test for the log-event idempotency key (FTY-096).

Proves the acceptance criteria: the 0015 migration applies cleanly on top of 0014
and is fully reversible, the ``idempotency_key`` column is nullable, and the
composite ``(user_id, idempotency_key)`` unique index exists. Runs against a
throwaway SQLite database.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from app.db import create_db_engine
from tests.conftest import downgrade, upgrade

_INDEX = "uq_log_events_user_idempotency_key"


def test_idempotency_key_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'idem.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)

        column = next(
            c for c in inspector.get_columns("log_events") if c["name"] == "idempotency_key"
        )
        assert column["nullable"] is True

        index = next(i for i in inspector.get_indexes("log_events") if i["name"] == _INDEX)
        assert index["unique"]
        assert index["column_names"] == ["user_id", "idempotency_key"]

        # Roll back only the 0015 migration; the column and index must be gone and
        # the prior log_events schema intact.
        downgrade(engine, "0014")
        after = inspect(engine)
        assert "idempotency_key" not in {c["name"] for c in after.get_columns("log_events")}
        assert _INDEX not in {i["name"] for i in after.get_indexes("log_events")}
        assert {"id", "user_id", "raw_text", "status", "created_at", "updated_at"} <= {
            c["name"] for c in after.get_columns("log_events")
        }
    finally:
        engine.dispose()
