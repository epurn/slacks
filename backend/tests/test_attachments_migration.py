"""Migration apply/rollback + cascade test for log_attachments (FTY-077).

Proves the acceptance criteria: the 0011 migration applies on top of the prior
schema and is fully reversible (additive — no prior table is dropped);
``log_attachments`` carries user + log-event ownership with cascading foreign keys;
and ``ON DELETE CASCADE`` from both the user and the owning log event actually
removes a saved attachment (exercised with SQLite foreign-key enforcement enabled,
not just asserted from metadata). Runs against a throwaway SQLite database.
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import event, inspect
from sqlalchemy.engine import Engine

from app.db import create_db_engine, create_session_factory
from app.enums import LogEventStatus
from app.models.attachments import LogAttachment
from app.models.identity import User
from app.models.log_events import LogEvent
from tests.conftest import downgrade, upgrade

_NEW_TABLES = {"log_attachments"}
_PRIOR_TABLES = {"users", "log_events", "saved_foods", "evidence_sources"}


def _enforce_foreign_keys(engine: Engine) -> None:
    """Turn on SQLite foreign-key enforcement for every connection from ``engine``."""

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_connection: object, _record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


def _saved_attachment(user_id: object, log_event_id: object) -> LogAttachment:
    return LogAttachment(
        user_id=user_id,
        log_event_id=log_event_id,
        content_type="image/png",
        byte_size=8,
        content_hash="0" * 64,
        data=b"\x89PNG\r\n\x1a\n",
    )


def test_log_attachments_migration_applies_and_rolls_back(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'attach.db'}")
    try:
        upgrade(engine, "head")
        applied = set(inspect(engine).get_table_names())
        assert _NEW_TABLES <= applied

        # Roll back only 0011; the prior schema must remain intact (additive).
        downgrade(engine, "0010")
        remaining = set(inspect(engine).get_table_names())
        assert not (_NEW_TABLES & remaining)
        assert _PRIOR_TABLES <= remaining
    finally:
        engine.dispose()


def test_log_attachments_carry_ownership_and_cascade_fks(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'owned.db'}")
    try:
        upgrade(engine, "head")
        inspector = inspect(engine)

        columns = {c["name"] for c in inspector.get_columns("log_attachments")}
        assert {
            "id",
            "user_id",
            "log_event_id",
            "content_type",
            "byte_size",
            "content_hash",
            "data",
            "created_at",
            "updated_at",
        } <= columns

        fks = {fk["referred_table"]: fk for fk in inspector.get_foreign_keys("log_attachments")}
        assert set(fks) == {"users", "log_events"}
        for table in ("users", "log_events"):
            assert fks[table].get("options", {}).get("ondelete", "").upper() == "CASCADE"
    finally:
        engine.dispose()


def test_deleting_user_cascades_attachments(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'user-cascade.db'}")
    _enforce_foreign_keys(engine)
    try:
        upgrade(engine, "head")
        factory = create_session_factory(engine)
        with factory() as session:
            user = User()
            session.add(user)
            session.flush()
            event_row = LogEvent(
                user_id=user.id, raw_text="label photo", status=LogEventStatus.PENDING
            )
            session.add(event_row)
            session.flush()
            session.add(_saved_attachment(user.id, event_row.id))
            session.commit()
            user_id = user.id

        with factory() as session:
            session.delete(session.get(User, user_id))
            session.commit()

        with factory() as session:
            assert session.query(LogAttachment).filter_by(user_id=user_id).count() == 0, (
                "log_attachments not cascaded on user deletion"
            )
    finally:
        engine.dispose()


def test_deleting_log_event_cascades_attachments(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'event-cascade.db'}")
    _enforce_foreign_keys(engine)
    try:
        upgrade(engine, "head")
        factory = create_session_factory(engine)
        with factory() as session:
            user = User()
            session.add(user)
            session.flush()
            event_row = LogEvent(
                user_id=user.id, raw_text="label photo", status=LogEventStatus.PENDING
            )
            session.add(event_row)
            session.flush()
            session.add(_saved_attachment(user.id, event_row.id))
            session.commit()
            event_id = event_row.id

        with factory() as session:
            session.delete(session.get(LogEvent, event_id))
            session.commit()

        with factory() as session:
            assert session.query(LogAttachment).filter_by(log_event_id=event_id).count() == 0, (
                "log_attachments not cascaded on log-event deletion"
            )
    finally:
        engine.dispose()
