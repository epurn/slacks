"""Migration apply/rollback + cascade test for saved foods/aliases (FTY-052).

Proves the acceptance criteria: the 0009 migration applies on top of the
corrections schema and is fully reversible; ``saved_foods`` and ``food_aliases``
carry user ownership with cascading foreign keys; and ``ON DELETE CASCADE`` from
the user actually removes a user's saved foods and aliases (exercised with SQLite
foreign-key enforcement enabled, not just asserted from metadata). Runs against a
throwaway SQLite database.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import event, inspect
from sqlalchemy.engine import Engine

from app.db import create_db_engine, create_session_factory
from app.enums import SavedFoodSource
from app.models.identity import User
from app.models.saved_foods import FoodAlias, SavedFood
from tests.conftest import downgrade, upgrade

_PRIOR_TABLES = {"users", "corrections", "derived_food_items", "derived_exercise_items"}
_NEW_TABLES = {"saved_foods", "food_aliases"}


def _enforce_foreign_keys(engine: Engine) -> None:
    """Turn on SQLite foreign-key enforcement for every connection from ``engine``."""

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def test_saved_foods_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'saved.db'}")
    try:
        upgrade(engine, "head")
        applied = set(inspect(engine).get_table_names())
        assert applied >= _NEW_TABLES

        # Roll back only 0009; the prior schema must remain intact.
        downgrade(engine, "0008")
        remaining = set(inspect(engine).get_table_names())
        assert not (_NEW_TABLES & remaining)
        assert remaining >= _PRIOR_TABLES
    finally:
        engine.dispose()


def test_saved_foods_carry_user_ownership_and_cascade_fks(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'owned.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)

        saved_columns = {c["name"] for c in inspector.get_columns("saved_foods")}
        assert {
            "user_id",
            "name",
            "name_normalized",
            "calories",
            "protein_g",
            "carbs_g",
            "fat_g",
            "serving_size",
            "serving_unit",
            "source",
        } <= saved_columns

        saved_fks = {fk["referred_table"]: fk for fk in inspector.get_foreign_keys("saved_foods")}
        assert saved_fks["users"].get("options", {}).get("ondelete", "").upper() == "CASCADE"

        alias_fks = {fk["referred_table"]: fk for fk in inspector.get_foreign_keys("food_aliases")}
        for table in ("users", "saved_foods"):
            assert alias_fks[table].get("options", {}).get("ondelete", "").upper() == "CASCADE"
    finally:
        engine.dispose()


def test_deleting_user_cascades_saved_foods_and_aliases(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'cascade.db'}")
    _enforce_foreign_keys(engine)
    try:
        upgrade(engine, "head")
        factory = create_session_factory(engine)
        with factory() as session:
            user = User()
            session.add(user)
            session.flush()
            saved = SavedFood(
                user_id=user.id,
                name="white rice",
                name_normalized="white rice",
                calories=200.0,
                protein_g=4.0,
                carbs_g=44.0,
                fat_g=0.4,
                serving_size=1.0,
                serving_unit="serving",
                source=SavedFoodSource.SAVED_FROM_CORRECTION,
            )
            session.add(saved)
            session.flush()
            session.add(
                FoodAlias(
                    user_id=user.id,
                    saved_food_id=saved.id,
                    alias="my usual rice",
                    alias_normalized="my usual rice",
                )
            )
            session.commit()
            user_id = user.id

        # Deleting the user must cascade away both the saved food and its alias.
        with factory() as session:
            session.delete(session.get(User, user_id))
            session.commit()

        with factory() as session:
            assert session.query(SavedFood).filter_by(user_id=user_id).count() == 0, (
                "saved_foods not cascaded on user deletion"
            )
            assert session.query(FoodAlias).filter_by(user_id=user_id).count() == 0, (
                "food_aliases not cascaded on user deletion"
            )
    finally:
        engine.dispose()


def test_deleting_saved_food_cascades_its_aliases(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'alias-cascade.db'}")
    _enforce_foreign_keys(engine)
    try:
        upgrade(engine, "head")
        factory = create_session_factory(engine)
        with factory() as session:
            user = User()
            session.add(user)
            session.flush()
            saved = SavedFood(
                user_id=user.id,
                name="oat milk",
                name_normalized="oat milk",
                calories=120.0,
                protein_g=3.0,
                carbs_g=16.0,
                fat_g=5.0,
                serving_size=250.0,
                serving_unit="ml",
                source=SavedFoodSource.SAVED_FROM_CORRECTION,
            )
            session.add(saved)
            session.flush()
            session.add(
                FoodAlias(
                    user_id=user.id,
                    saved_food_id=saved.id,
                    alias="oatly",
                    alias_normalized="oatly",
                )
            )
            session.commit()
            saved_id: uuid.UUID = saved.id

        with factory() as session:
            session.delete(session.get(SavedFood, saved_id))
            session.commit()

        with factory() as session:
            assert session.query(FoodAlias).filter_by(saved_food_id=saved_id).count() == 0
    finally:
        engine.dispose()
