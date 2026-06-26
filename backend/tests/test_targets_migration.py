"""Migration apply/rollback test for the goals/daily_targets schema (FTY-022).

Proves the acceptance criteria: the 0002 migration applies cleanly on top of the
baseline and is fully reversible, and the derived tables carry user ownership.
Runs against a throwaway SQLite database.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from app.db import create_db_engine
from tests.conftest import downgrade, upgrade

_NEW_TABLES = {"goals", "daily_targets"}
_BASELINE_TABLES = {"users", "auth_identities", "user_profiles"}


def test_targets_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'targets.db'}")
    try:
        upgrade(engine, "head")
        applied = set(inspect(engine).get_table_names())
        assert _NEW_TABLES <= applied

        # Roll back only the 0002 migration; the baseline must remain intact.
        downgrade(engine, "0001")
        remaining = set(inspect(engine).get_table_names())
        assert not (_NEW_TABLES & remaining)
        assert _BASELINE_TABLES <= remaining
    finally:
        engine.dispose()


def test_target_tables_carry_user_ownership(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'ownership.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)

        goal_cols = {c["name"] for c in inspector.get_columns("goals")}
        target_cols = {c["name"] for c in inspector.get_columns("daily_targets")}
        assert "user_id" in goal_cols
        assert {"user_id", "goal_id"} <= target_cols

        # Ownership foreign keys cascade from the owning user (and goal).
        goal_fk_targets = {fk["referred_table"] for fk in inspector.get_foreign_keys("goals")}
        target_fk_targets = {
            fk["referred_table"] for fk in inspector.get_foreign_keys("daily_targets")
        }
        assert "users" in goal_fk_targets
        assert {"users", "goals"} <= target_fk_targets

        # Ownership deletes cascade: removing a user (or goal) removes derived rows.
        all_fks = inspector.get_foreign_keys("goals") + inspector.get_foreign_keys("daily_targets")
        ondeletes = {fk.get("options", {}).get("ondelete", "").upper() for fk in all_fks}
        assert ondeletes == {"CASCADE"}
    finally:
        engine.dispose()
