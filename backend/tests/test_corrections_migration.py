"""Migration apply/rollback tests for the corrections schema (FTY-051, FTY-377).

Proves the acceptance criteria: the 0008 migration applies on top of the
food-resolution schema and is fully reversible; ``corrections`` carries user
ownership with cascading foreign keys and a single-typed-reference check; and the
derived-item tables gain the nullable estimated/original snapshot columns. The
0021 migration (FTY-377) generalizes the audit to value-type-polymorphic rows —
nullable ``new_value``, the ``old_value_text``/``new_value_text`` columns, and the
one-value-kind check constraint that accepts a numeric-only or text-only row and
rejects both/neither — and rolls back cleanly. Runs against a throwaway SQLite
database; the Postgres-parity chain lives in ``test_postgres_migration.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine import Engine
from sqlalchemy.engine.interfaces import ReflectedColumn

from app.db import create_db_engine
from tests.conftest import downgrade, upgrade
from tests.corrections_helpers import assert_one_value_kind_constraint

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
        assert food_columns >= _FOOD_SNAPSHOT_COLUMNS
        exercise_columns = {
            c["name"] for c in inspect(engine).get_columns("derived_exercise_items")
        }
        assert _EXERCISE_SNAPSHOT_COLUMN in exercise_columns

        # Roll back only 0008; the prior schema must remain intact.
        downgrade(engine, "0007")
        remaining = set(inspect(engine).get_table_names())
        assert "corrections" not in remaining
        assert remaining >= _PRIOR_TABLES
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


def _corrections_columns(engine: Engine) -> dict[str, ReflectedColumn]:
    return {c["name"]: c for c in inspect(engine).get_columns("corrections")}


def test_polymorphic_values_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    """The 0021 migration (FTY-377) round-trips and reshapes the value columns."""

    engine = create_db_engine(f"sqlite:///{tmp_path / 'poly.db'}")
    try:
        upgrade(engine, "head")
        columns = _corrections_columns(engine)
        assert {"old_value_text", "new_value_text"} <= set(columns)
        assert columns["new_value"]["nullable"] is True
        for name in ("old_value_text", "new_value_text"):
            assert columns[name]["nullable"] is True
            assert isinstance(columns[name]["type"], sa.String)
        checks = {c["name"] for c in inspect(engine).get_check_constraints("corrections")}
        # The new one-value-kind check joins — and does not displace — the
        # single-item-reference check.
        assert {"ck_corrections_one_value_kind", "ck_corrections_one_item_reference"} <= checks

        # Roll back only 0021; the numeric-only audit shape is restored.
        downgrade(engine, "0020")
        rolled = _corrections_columns(engine)
        assert not ({"old_value_text", "new_value_text"} & set(rolled))
        assert rolled["new_value"]["nullable"] is False
        rolled_checks = {c["name"] for c in inspect(engine).get_check_constraints("corrections")}
        assert "ck_corrections_one_value_kind" not in rolled_checks
        assert "ck_corrections_one_item_reference" in rolled_checks

        # And the upgrade re-applies cleanly on top of the rollback.
        upgrade(engine, "head")
        assert "new_value_text" in _corrections_columns(engine)
    finally:
        engine.dispose()


def test_downgrade_removes_text_valued_rows_before_not_null_restore(tmp_path: Path) -> None:
    """A dev database holding ``name_edit`` rows still downgrades cleanly (FTY-377)."""

    engine = create_db_engine(f"sqlite:///{tmp_path / 'poly-down.db'}")
    try:
        upgrade(engine, "head")
        with engine.begin() as connection:
            connection.execute(
                sa.text(
                    "INSERT INTO corrections (id, user_id, item_type, field, new_value,"
                    " old_value_text, new_value_text, source, created_at,"
                    " derived_food_item_id)"
                    " VALUES (:id, :user_id, 'food', 'name', NULL, 'old', 'new',"
                    " 'name_edit', :created_at, :item_id)"
                ),
                {
                    # SQLite enforces no FKs by default, so bare ids suffice here.
                    "id": uuid.uuid4().hex,
                    "user_id": uuid.uuid4().hex,
                    "item_id": uuid.uuid4().hex,
                    "created_at": datetime.now(UTC).isoformat(),
                },
            )

        downgrade(engine, "0020")
        with engine.connect() as connection:
            remaining = connection.execute(sa.text("SELECT COUNT(*) FROM corrections")).scalar()
        assert remaining == 0
    finally:
        engine.dispose()


def test_value_kind_check_constraint_enforced(tmp_path: Path) -> None:
    """Numeric-only and text-only rows insert; both/neither are rejected (FTY-377)."""

    engine = create_db_engine(f"sqlite:///{tmp_path / 'poly-check.db'}")
    try:
        upgrade(engine, "head")
        assert_one_value_kind_constraint(engine)
    finally:
        engine.dispose()
