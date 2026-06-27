"""Migration apply/rollback test for the food-resolution schema (FTY-044).

Proves the acceptance criteria: the 0007 migration applies on top of the
exercise-burn schema and is fully reversible; ``products`` is a global cache with
**no** user ownership while ``evidence_sources`` carries user ownership with
cascading foreign keys; and ``derived_food_items`` gains the nullable resolution
columns. Runs against a throwaway SQLite database.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from app.db import create_db_engine
from tests.conftest import downgrade, upgrade

_NEW_TABLES = {"products", "evidence_sources"}
_PRIOR_TABLES = {"users", "log_events", "derived_food_items", "derived_exercise_items"}
_FOOD_RESOLUTION_COLUMNS = {"grams", "calories", "protein_g", "carbs_g", "fat_g"}


def test_food_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'food.db'}")
    try:
        upgrade(engine, "head")
        applied = set(inspect(engine).get_table_names())
        assert _NEW_TABLES <= applied
        food_columns = {c["name"] for c in inspect(engine).get_columns("derived_food_items")}
        assert _FOOD_RESOLUTION_COLUMNS <= food_columns

        # Roll back only 0007; the prior schema must remain intact.
        downgrade(engine, "0006")
        remaining = set(inspect(engine).get_table_names())
        assert not (_NEW_TABLES & remaining)
        assert _PRIOR_TABLES <= remaining
        rolled_back = {c["name"] for c in inspect(engine).get_columns("derived_food_items")}
        assert not (_FOOD_RESOLUTION_COLUMNS & rolled_back)
    finally:
        engine.dispose()


def test_products_is_global_with_no_user_ownership(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'products.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)

        columns = {c["name"] for c in inspector.get_columns("products")}
        # Global source facts: no user_id, and the per-100g facts are present.
        assert "user_id" not in columns
        assert {
            "source",
            "query_key",
            "source_ref",
            "calories_per_100g",
            "protein_per_100g",
            "carbs_per_100g",
            "fat_per_100g",
            "content_hash",
        } <= columns
        # No foreign keys to user-owned tables.
        assert inspector.get_foreign_keys("products") == []
    finally:
        engine.dispose()


def test_products_barcode_key_applies_and_rolls_back(tmp_path: Path) -> None:
    # FTY-060: the additive barcode key on the global products cache applies and
    # rolls back, leaving the FTY-044 products schema intact.
    engine = create_db_engine(f"sqlite:///{tmp_path / 'barcode.db'}")
    try:
        upgrade(engine, "head")
        columns = {c["name"] for c in inspect(engine).get_columns("products")}
        assert "barcode" in columns
        indexes = {ix["name"] for ix in inspect(engine).get_indexes("products")}
        assert "ix_products_barcode" in indexes
        # The barcode key is global source data: products still has no user_id.
        assert "user_id" not in columns

        downgrade(engine, "0009")
        rolled_back = {c["name"] for c in inspect(engine).get_columns("products")}
        assert "barcode" not in rolled_back
        # The FTY-044 products table itself survives the 0010 rollback.
        assert "products" in set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_evidence_sources_carries_user_ownership_and_cascades(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'evidence.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)

        columns = {c["name"] for c in inspector.get_columns("evidence_sources")}
        assert {"user_id", "log_event_id", "derived_food_item_id", "content_hash"} <= columns

        fks = {fk["referred_table"]: fk for fk in inspector.get_foreign_keys("evidence_sources")}
        # Ownership + cascade from the user, the log event, and the derived item.
        for table in ("users", "log_events", "derived_food_items"):
            assert fks[table].get("options", {}).get("ondelete", "").upper() == "CASCADE"
        # The global product link is severed (SET NULL), never cascaded, on cache clear.
        assert fks["products"].get("options", {}).get("ondelete", "").upper() == "SET NULL"
    finally:
        engine.dispose()
