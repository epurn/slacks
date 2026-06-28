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


_DERIVED_MACRO_COLUMNS = {"protein_target_g", "carbs_target_g", "fat_target_g", "macros_clamped"}
_OVERRIDE_COLUMNS = {
    "override_calorie_target_kcal",
    "override_protein_target_g",
    "override_carbs_target_g",
    "override_fat_target_g",
    "override_set_at",
}


def test_override_columns_apply_and_rollback(tmp_path: Path) -> None:
    """FTY-095: override + persisted-derived-macro columns apply on top of 0013 and roll back.

    Layered on FTY-094's revision: upgrading to head adds the nullable override
    columns and the NOT NULL derived macro columns; ``downgrade -1`` (to 0013)
    drops exactly those columns while leaving ``daily_targets`` and its FTY-022
    derived columns intact.
    """

    engine = create_db_engine(f"sqlite:///{tmp_path / 'override.db'}")
    try:
        upgrade(engine, "head")
        cols = {c["name"] for c in inspect(engine).get_columns("daily_targets")}
        assert _DERIVED_MACRO_COLUMNS <= cols
        assert _OVERRIDE_COLUMNS <= cols

        # The derived macro columns are NOT NULL; the override columns are nullable.
        col_meta = {c["name"]: c for c in inspect(engine).get_columns("daily_targets")}
        assert all(not col_meta[name]["nullable"] for name in _DERIVED_MACRO_COLUMNS)
        assert all(col_meta[name]["nullable"] for name in _OVERRIDE_COLUMNS)

        downgrade(engine, "0013")
        remaining = {c["name"] for c in inspect(engine).get_columns("daily_targets")}
        assert not (_OVERRIDE_COLUMNS & remaining)
        assert not (_DERIVED_MACRO_COLUMNS & remaining)
        # The table and its FTY-022 derived columns survive the rollback.
        assert {"daily_calorie_target_kcal", "clamped"} <= remaining
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
