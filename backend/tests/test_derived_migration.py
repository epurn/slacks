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
