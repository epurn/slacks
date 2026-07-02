"""Migration apply/rollback test for the derived-parse schema (FTY-042).

Proves the acceptance criteria: the 0005 migration applies on top of the
estimation schema and is fully reversible, and the three new tables carry user
ownership with cascading foreign keys. Runs against a throwaway SQLite database.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import inspect

from app.db import create_db_engine
from tests.conftest import downgrade, upgrade

_NEW_TABLES = {"derived_food_items", "derived_exercise_items", "clarification_questions"}
_PRIOR_TABLES = {
    "users",
    "log_events",
    "estimation_jobs",
    "estimation_runs",
}


def test_derived_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'derived.db'}")
    try:
        upgrade(engine, "head")
        applied = set(inspect(engine).get_table_names())
        assert _NEW_TABLES <= applied

        # Roll back only the 0005 migration; the prior schema must remain intact.
        downgrade(engine, "0004")
        remaining = set(inspect(engine).get_table_names())
        assert not (_NEW_TABLES & remaining)
        assert _PRIOR_TABLES <= remaining
    finally:
        engine.dispose()


@pytest.mark.parametrize("table", sorted(_NEW_TABLES))
def test_derived_tables_carry_user_ownership(tmp_path: Path, table: str) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'owned.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)

        columns = {c["name"] for c in inspector.get_columns(table)}
        assert {"id", "log_event_id", "user_id", "created_at", "updated_at"} <= columns

        # Object-level ownership + cascade from both the user and the log event.
        referred = {fk["referred_table"] for fk in inspector.get_foreign_keys(table)}
        assert referred == {"users", "log_events"}
        ondeletes = {
            fk.get("options", {}).get("ondelete", "").upper()
            for fk in inspector.get_foreign_keys(table)
        }
        assert ondeletes == {"CASCADE"}
    finally:
        engine.dispose()


def test_derived_item_tables_have_candidate_columns(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'cols.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)
        for table in ("derived_food_items", "derived_exercise_items"):
            columns = {c["name"] for c in inspector.get_columns(table)}
            assert {"name", "quantity_text", "unit", "amount", "status"} <= columns
    finally:
        engine.dispose()


def test_clarification_questions_options_migration_applies_and_rolls_back(
    tmp_path: Path,
) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'question-options.db'}")
    try:
        upgrade(engine, "head")
        columns = {c["name"]: c for c in inspect(engine).get_columns("clarification_questions")}
        assert "options" in columns
        assert not columns["options"]["nullable"]

        downgrade(engine, "0016")
        rolled_back = {c["name"] for c in inspect(engine).get_columns("clarification_questions")}
        assert "options" not in rolled_back
    finally:
        engine.dispose()


def test_exercise_active_calories_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    # FTY-043 adds derived_exercise_items.active_calories (0006); it applies on top of
    # the derived-parse schema and rolls back to 0005 without touching food items.
    engine = create_db_engine(f"sqlite:///{tmp_path / 'burn.db'}")
    try:
        upgrade(engine, "head")
        exercise_columns = {
            c["name"] for c in inspect(engine).get_columns("derived_exercise_items")
        }
        assert "active_calories" in exercise_columns
        # The column is exercise-only; food items do not gain a burn column.
        food_columns = {c["name"] for c in inspect(engine).get_columns("derived_food_items")}
        assert "active_calories" not in food_columns

        downgrade(engine, "0005")
        rolled_back = {c["name"] for c in inspect(engine).get_columns("derived_exercise_items")}
        assert "active_calories" not in rolled_back
    finally:
        engine.dispose()
