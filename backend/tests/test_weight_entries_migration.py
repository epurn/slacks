"""Migration apply/rollback test for the weight_entries schema (FTY-070).

Proves the acceptance criteria: the 0013 migration applies cleanly on top of the
evidence-assumptions schema and is fully reversible, and the table carries user
ownership with a cascading foreign key. Runs against a throwaway SQLite database.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from app.db import create_db_engine
from tests.conftest import downgrade, upgrade

_NEW_TABLES = {"weight_entries"}
_PRIOR_TABLES = {"users", "auth_identities", "user_profiles", "log_events"}


def test_weight_entries_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'weight_entries.db'}")
    try:
        upgrade(engine, "head")
        applied = set(inspect(engine).get_table_names())
        assert _NEW_TABLES <= applied

        # Roll back only the 0013 migration; the prior schema must remain intact.
        downgrade(engine, "0012")
        remaining = set(inspect(engine).get_table_names())
        assert not (_NEW_TABLES & remaining)
        assert _PRIOR_TABLES <= remaining
    finally:
        engine.dispose()


def test_weight_entries_carry_user_ownership(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'ownership.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)

        columns = {c["name"] for c in inspector.get_columns("weight_entries")}
        assert {
            "id",
            "user_id",
            "weight_kg",
            "effective_date",
            "created_at",
            "updated_at",
        } <= columns

        fks = inspector.get_foreign_keys("weight_entries")
        assert {fk["referred_table"] for fk in fks} == {"users"}
        ondeletes = {fk.get("options", {}).get("ondelete", "").upper() for fk in fks}
        assert ondeletes == {"CASCADE"}
    finally:
        engine.dispose()
