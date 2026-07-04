"""Migration apply/rollback test for the log_events schema (FTY-030).

Proves the acceptance criteria: the 0003 migration applies cleanly on top of the
goals/targets schema and is fully reversible, and the table carries user
ownership with a cascading foreign key. Runs against a throwaway SQLite database.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from app.db import create_db_engine
from tests.conftest import downgrade, upgrade

_NEW_TABLES = {"log_events"}
_PRIOR_TABLES = {"users", "auth_identities", "user_profiles", "goals", "daily_targets"}


def test_log_events_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'log_events.db'}")
    try:
        upgrade(engine, "head")
        applied = set(inspect(engine).get_table_names())
        assert applied >= _NEW_TABLES

        # Roll back only the 0003 migration; the prior schema must remain intact.
        downgrade(engine, "0002")
        remaining = set(inspect(engine).get_table_names())
        assert not (_NEW_TABLES & remaining)
        assert remaining >= _PRIOR_TABLES
    finally:
        engine.dispose()


def test_log_events_carry_user_ownership(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'ownership.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)

        columns = {c["name"] for c in inspector.get_columns("log_events")}
        assert {"id", "user_id", "raw_text", "status", "created_at", "updated_at"} <= columns

        fks = inspector.get_foreign_keys("log_events")
        assert {fk["referred_table"] for fk in fks} == {"users"}
        ondeletes = {fk.get("options", {}).get("ondelete", "").upper() for fk in fks}
        assert ondeletes == {"CASCADE"}
    finally:
        engine.dispose()
