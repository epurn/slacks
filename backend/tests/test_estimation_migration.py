"""Migration apply/rollback test for the estimation schema (FTY-040).

Proves the acceptance criteria: the 0004 migration applies cleanly on top of the
log-events schema and is fully reversible, and both new tables carry user
ownership with cascading foreign keys. Runs against a throwaway SQLite database.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from app.db import create_db_engine
from tests.conftest import downgrade, upgrade

_NEW_TABLES = {"estimation_jobs", "estimation_runs"}
_PRIOR_TABLES = {
    "users",
    "auth_identities",
    "user_profiles",
    "goals",
    "daily_targets",
    "log_events",
}


def test_estimation_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'estimation.db'}")
    try:
        upgrade(engine, "head")
        applied = set(inspect(engine).get_table_names())
        assert applied >= _NEW_TABLES

        # Roll back only the 0004 migration; the prior schema must remain intact.
        downgrade(engine, "0003")
        remaining = set(inspect(engine).get_table_names())
        assert not (_NEW_TABLES & remaining)
        assert remaining >= _PRIOR_TABLES
    finally:
        engine.dispose()


def test_estimation_jobs_carry_user_ownership(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)

        columns = {c["name"] for c in inspector.get_columns("estimation_jobs")}
        assert {
            "id",
            "log_event_id",
            "user_id",
            "status",
            "attempts",
            "max_attempts",
            "idempotency_key",
            "created_at",
            "updated_at",
        } <= columns

        # Ownership + cascade from both the user and the owning log event.
        referred = {fk["referred_table"] for fk in inspector.get_foreign_keys("estimation_jobs")}
        assert referred == {"users", "log_events"}
        ondeletes = {
            fk.get("options", {}).get("ondelete", "").upper()
            for fk in inspector.get_foreign_keys("estimation_jobs")
        }
        assert ondeletes == {"CASCADE"}

        # One job per event: log_event_id is unique (the idempotency anchor).
        unique_cols = {
            tuple(uc["column_names"]) for uc in inspector.get_unique_constraints("estimation_jobs")
        }
        assert ("log_event_id",) in unique_cols
    finally:
        engine.dispose()


def test_estimation_runs_carry_user_ownership(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'runs.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)

        columns = {c["name"] for c in inspector.get_columns("estimation_runs")}
        assert {
            "id",
            "job_id",
            "log_event_id",
            "user_id",
            "attempt",
            "status",
            "provider",
            "model",
            "schema_version",
            "tool_names",
            "source_refs",
            "assumptions",
            "validation_errors",
            "trace",
            "error",
            "created_at",
            "updated_at",
        } <= columns

        referred = {fk["referred_table"] for fk in inspector.get_foreign_keys("estimation_runs")}
        assert referred == {"users", "log_events", "estimation_jobs"}
        ondeletes = {
            fk.get("options", {}).get("ondelete", "").upper()
            for fk in inspector.get_foreign_keys("estimation_runs")
        }
        assert ondeletes == {"CASCADE"}
    finally:
        engine.dispose()
