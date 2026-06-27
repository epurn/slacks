"""Migration apply/rollback test for the corrections + snapshot schema (FTY-051).

Proves the acceptance criteria: the 0008 migration applies on top of the
food-resolution schema and is fully reversible; ``corrections`` carries user
ownership with cascading foreign keys and a single-typed-reference check; and the
derived-item tables gain the nullable estimated/original snapshot columns. Runs
against a throwaway SQLite database.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from app.db import create_db_engine
from tests.conftest import downgrade, upgrade

_FOOD_SNAPSHOT_COLUMNS = {
    "calories_estimated",
    "protein_g_estimated",
    "carbs_g_estimated",
    "fat_g_estimated",
}
_EXERCISE_SNAPSHOT_COLUMN = "active_calories_estimated"
_PRIOR_TABLES = {"users", "log_events", "derived_food_items", "derived_exercise_items"}


def test_corrections_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'corr.db'}")
    try:
        upgrade(engine, "head")
        applied = set(inspect(engine).get_table_names())
        assert "corrections" in applied

        food_columns = {c["name"] for c in inspect(engine).get_columns("derived_food_items")}
        assert _FOOD_SNAPSHOT_COLUMNS <= food_columns
        exercise_columns = {
            c["name"] for c in inspect(engine).get_columns("derived_exercise_items")
        }
        assert _EXERCISE_SNAPSHOT_COLUMN in exercise_columns

        # Roll back only 0008; the prior schema must remain intact.
        downgrade(engine, "0007")
        remaining = set(inspect(engine).get_table_names())
        assert "corrections" not in remaining
        assert _PRIOR_TABLES <= remaining
        rolled_food = {c["name"] for c in inspect(engine).get_columns("derived_food_items")}
        assert not (_FOOD_SNAPSHOT_COLUMNS & rolled_food)
        rolled_exercise = {c["name"] for c in inspect(engine).get_columns("derived_exercise_items")}
        assert _EXERCISE_SNAPSHOT_COLUMN not in rolled_exercise
    finally:
        engine.dispose()


def test_corrections_carries_user_ownership_and_typed_item_refs(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'owned.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)

        columns = {c["name"] for c in inspector.get_columns("corrections")}
        assert {
            "user_id",
            "item_type",
            "derived_food_item_id",
            "derived_exercise_item_id",
            "field",
            "old_value",
            "new_value",
            "source",
            "created_at",
        } <= columns

        fks = {fk["referred_table"]: fk for fk in inspector.get_foreign_keys("corrections")}
        # Object-level ownership + cascade from the user and both typed item refs.
        for table in ("users", "derived_food_items", "derived_exercise_items"):
            assert fks[table].get("options", {}).get("ondelete", "").upper() == "CASCADE"
    finally:
        engine.dispose()


def test_corrections_has_single_item_reference_check(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'check.db'}")
    try:
        upgrade(engine, "head")
        checks = {c["name"] for c in inspect(engine).get_check_constraints("corrections")}
        assert "ck_corrections_one_item_reference" in checks
    finally:
        engine.dispose()
