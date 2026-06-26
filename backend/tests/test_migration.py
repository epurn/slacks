"""Migration apply/rollback test for the baseline identity schema.

Proves the acceptance criteria: the baseline migration applies cleanly and is
fully reversible. Runs against a throwaway SQLite database.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from app.db import create_db_engine
from tests.conftest import downgrade, upgrade

_TABLES = {"users", "auth_identities", "user_profiles"}


def test_baseline_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    try:
        upgrade(engine, "head")
        applied = set(inspect(engine).get_table_names())
        assert _TABLES <= applied

        downgrade(engine, "base")
        remaining = set(inspect(engine).get_table_names())
        assert not (_TABLES & remaining)
    finally:
        engine.dispose()


def test_auth_identities_are_separate_from_users(tmp_path: Path) -> None:
    # The security baseline requires credentials to live apart from the user row:
    # the password hash column must exist on auth_identities, not on users.
    engine = create_db_engine(f"sqlite:///{tmp_path / 'separation.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)
        user_cols = {c["name"] for c in inspector.get_columns("users")}
        identity_cols = {c["name"] for c in inspector.get_columns("auth_identities")}

        assert "password_hash" not in user_cols
        assert "password_hash" in identity_cols
        assert "user_id" in identity_cols
    finally:
        engine.dispose()
