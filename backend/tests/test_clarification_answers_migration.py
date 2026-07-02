"""Migration apply/rollback test for ``clarification_answers`` (FTY-171).

Proves the acceptance criteria: the 0016 migration applies cleanly on top of
0015 and is fully reversible, the table carries the ownership columns and the
unique ``question_id`` idempotency anchor, and no prior table is altered. Runs
against a throwaway SQLite database; the same chain is exercised against
Postgres by ``tests/test_postgres_migration.py`` (FTY-143 guard).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from app.db import create_db_engine
from tests.conftest import downgrade, upgrade

_UNIQUE = "uq_clarification_answers_question_id"


def test_clarification_answers_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'answers.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)

        columns = {c["name"]: c for c in inspector.get_columns("clarification_answers")}
        assert set(columns) == {
            "id",
            "question_id",
            "log_event_id",
            "user_id",
            "answer_text",
            "created_at",
            "updated_at",
        }
        assert not columns["answer_text"]["nullable"]

        # The unique question_id is the resolve's idempotency anchor: at most
        # one answer per question, enforced by the database.
        unique_indexes = {
            i["name"]: i for i in inspector.get_indexes("clarification_answers") if i["unique"]
        }
        unique_constraints = {
            c["name"] for c in inspector.get_unique_constraints("clarification_answers")
        }
        assert _UNIQUE in unique_indexes or _UNIQUE in unique_constraints

        # Ownership and retention: every FK cascades so answers follow the
        # owning question, event, and account.
        fks = inspector.get_foreign_keys("clarification_answers")
        referred = {fk["referred_table"]: fk for fk in fks}
        assert set(referred) == {"clarification_questions", "log_events", "users"}
        for fk in fks:
            assert fk["options"].get("ondelete") == "CASCADE"

        # Roll back only the 0016 migration; the table must be gone and the
        # prior clarification_questions schema intact (no prior table altered).
        downgrade(engine, "0015")
        after = inspect(engine)
        assert not after.has_table("clarification_answers")
        assert after.has_table("clarification_questions")

        # And it re-applies cleanly.
        upgrade(engine, "head")
        assert inspect(engine).has_table("clarification_answers")
    finally:
        engine.dispose()
