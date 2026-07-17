"""Postgres-exercised migration guard (FTY-143).

The automated migration gate runs against SQLite, which silently tolerates DDL
that Postgres rejects — e.g. a ``BOOLEAN`` column with an integer-literal server
default (``BOOLEAN DEFAULT 0``). That gap let migration ``0014`` ship a default
that made the entire macro-target feature dead on every Postgres deploy
(``DatatypeMismatch`` → migration never applies → ``UndefinedColumn`` 500s).

This module runs the **full migration chain** against a real Postgres engine —
``upgrade head`` → ``downgrade base`` → ``upgrade head`` — and asserts the
``daily_targets`` columns from ``0014`` exist with the expected types and
nullability. It is the regression guard for that class of SQLite-only-tolerant
DDL: it fails on the original ``BOOLEAN DEFAULT 0`` (the first ``upgrade head``
raises ``DatatypeMismatch``) and passes on the corrected ``DEFAULT false``.

It is opt-in: the ``pg_engine`` fixture skips the test when
``SLACKS_TEST_DATABASE_URL`` is unset, so a fresh checkout and the SQLite-only
local/CI path stay green without a running Postgres. CI wires the env var against
a real Postgres service in FTY-144.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from tests.conftest import downgrade, upgrade
from tests.corrections_helpers import assert_one_value_kind_constraint

# 0014 columns, grouped by the contract they must satisfy on Postgres.
_DERIVED_INT_COLUMNS = {"protein_target_g", "carbs_target_g", "fat_target_g"}
_DERIVED_BOOL_COLUMN = "macros_clamped"
_OVERRIDE_NULLABLE_COLUMNS = {
    "override_calorie_target_kcal",
    "override_protein_target_g",
    "override_carbs_target_g",
    "override_fat_target_g",
    "override_set_at",
}


def test_full_chain_applies_on_postgres(pg_engine: Engine) -> None:
    """The full migration chain round-trips on Postgres and yields the 0014 shape.

    Exercises ``upgrade head`` → ``downgrade base`` → ``upgrade head``. The first
    upgrade is what failed under ``BOOLEAN DEFAULT 0`` (``DatatypeMismatch``); the
    column assertions after the final upgrade confirm the persisted-derived and
    override columns land with the documented types and nullability.
    """

    upgrade(pg_engine, "head")
    downgrade(pg_engine, "base")
    # The columns are gone after a full teardown.
    assert "daily_targets" not in set(inspect(pg_engine).get_table_names())
    upgrade(pg_engine, "head")

    col_meta = {c["name"]: c for c in inspect(pg_engine).get_columns("daily_targets")}

    # All 0014 columns are present.
    expected = _DERIVED_INT_COLUMNS | {_DERIVED_BOOL_COLUMN} | _OVERRIDE_NULLABLE_COLUMNS
    assert expected <= set(col_meta)

    # Persisted-derived columns are NOT NULL; the integer ones are integer-typed
    # and the boolean one is boolean-typed (the bug: a boolean column whose
    # default was an integer literal).
    for name in _DERIVED_INT_COLUMNS:
        assert not col_meta[name]["nullable"], name
        assert isinstance(col_meta[name]["type"], sa.Integer), name
    assert not col_meta[_DERIVED_BOOL_COLUMN]["nullable"]
    assert isinstance(col_meta[_DERIVED_BOOL_COLUMN]["type"], sa.Boolean)

    # User-override columns are nullable (NULL while the target is derived).
    for name in _OVERRIDE_NULLABLE_COLUMNS:
        assert col_meta[name]["nullable"], name


def test_corrections_polymorphic_values_on_postgres(pg_engine: Engine) -> None:
    """The 0021 corrections generalization round-trips on Postgres (FTY-377).

    Alembic's batch alter runs as real ``ALTER TABLE`` statements on Postgres (no
    SQLite-style table recreate), and relaxing ``new_value``'s NOT NULL plus the
    new check constraint is exactly the DDL class SQLite tolerates permissively —
    so the shape, the constraint's runtime enforcement, and the rollback (which
    restores NOT NULL after deleting text-valued rows) are proven against the
    production engine, not just the test one.
    """

    upgrade(pg_engine, "head")

    col_meta = {c["name"]: c for c in inspect(pg_engine).get_columns("corrections")}
    assert col_meta["new_value"]["nullable"] is True
    for name in ("old_value_text", "new_value_text"):
        assert col_meta[name]["nullable"] is True, name
        assert isinstance(col_meta[name]["type"], sa.String), name
    checks = {c["name"] for c in inspect(pg_engine).get_check_constraints("corrections")}
    assert {"ck_corrections_one_value_kind", "ck_corrections_one_item_reference"} <= checks

    # The constraint enforces at insert time: numeric-only and text-only rows are
    # accepted, a row with both or neither value kind is rejected.
    assert_one_value_kind_constraint(pg_engine)

    # Rollback restores the numeric-only NOT NULL shape (deleting the dev-only
    # text-valued rows first), and the upgrade re-applies on top of it.
    downgrade(pg_engine, "0020")
    rolled = {c["name"]: c for c in inspect(pg_engine).get_columns("corrections")}
    assert "new_value_text" not in rolled
    assert rolled["new_value"]["nullable"] is False
    upgrade(pg_engine, "head")
