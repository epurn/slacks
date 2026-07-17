"""Migration apply/rollback test for the ``0022`` transient marker (FTY-375).

Proves the acceptance criteria for the ``log_attachments.transient`` column
(``log-attachments.md`` v3): the migration applies on top of ``0021`` and rolls
back cleanly (additive — no other column or table changes); a row that existed
**before** the upgrade — the FTY-077/FTY-306 explicit-save class — is backfilled
to ``transient = false`` by the server default, so prior saved attachments are
unaffected. Runs against a throwaway SQLite database; the full chain is
exercised on Postgres by the FTY-143 migration guard
(``test_postgres_migration.py``).
"""

from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db import create_db_engine
from tests.conftest import downgrade, upgrade

_PNG_BYTES = b"\x89PNG\r\n\x1a\n"


def _seed_pre_0022_attachment(engine: Engine) -> uuid.UUID:
    """Insert a user, event, and saved attachment against the 0021 schema."""

    user_id, event_id, attachment_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, created_at, updated_at) "
                "VALUES (:id, '2026-07-17 00:00:00', '2026-07-17 00:00:00')"
            ),
            {"id": str(user_id)},
        )
        connection.execute(
            text(
                "INSERT INTO log_events (id, user_id, raw_text, status, created_at, updated_at) "
                "VALUES (:id, :uid, 'label photo', 'pending', "
                "'2026-07-17 00:00:00', '2026-07-17 00:00:00')"
            ),
            {"id": str(event_id), "uid": str(user_id)},
        )
        connection.execute(
            text(
                "INSERT INTO log_attachments "
                "(id, user_id, log_event_id, content_type, byte_size, content_hash, data, "
                "created_at, updated_at) "
                "VALUES (:id, :uid, :eid, 'image/png', :size, :hash, :data, "
                "'2026-07-17 00:00:00', '2026-07-17 00:00:00')"
            ),
            {
                "id": str(attachment_id),
                "uid": str(user_id),
                "eid": str(event_id),
                "size": len(_PNG_BYTES),
                "hash": "0" * 64,
                "data": _PNG_BYTES,
            },
        )
    return attachment_id


def test_transient_migration_applies_backfills_false_and_rolls_back(tmp_path: Path) -> None:
    engine = create_db_engine(f"sqlite:///{tmp_path / 'transient.db'}")
    try:
        # Seed a saved attachment on the prior schema, then apply 0022 on top.
        upgrade(engine, "0021")
        attachment_id = _seed_pre_0022_attachment(engine)
        upgrade(engine, "0022")

        columns = {c["name"]: c for c in inspect(engine).get_columns("log_attachments")}
        assert "transient" in columns
        assert columns["transient"]["nullable"] is False

        with engine.connect() as connection:
            # The pre-existing explicit-save row defaults to non-transient.
            stored = connection.execute(
                text("SELECT transient FROM log_attachments WHERE id = :id"),
                {"id": str(attachment_id)},
            ).scalar_one()
            assert not stored
            # The server default covers inserts that omit the column entirely.
            connection.execute(
                text(
                    "INSERT INTO log_attachments "
                    "(id, user_id, log_event_id, content_type, byte_size, content_hash, data, "
                    "created_at, updated_at) "
                    "SELECT :id, user_id, log_event_id, content_type, byte_size, content_hash, "
                    "data, created_at, updated_at FROM log_attachments WHERE id = :src"
                ),
                {"id": str(uuid.uuid4()), "src": str(attachment_id)},
            )
            defaulted = connection.execute(
                text("SELECT COUNT(*) FROM log_attachments WHERE transient = 0")
            ).scalar_one()
            assert defaulted == 2
            connection.commit()

        # Roll back only 0022: the column is dropped, the rows and the prior
        # schema remain intact (additive, reversible).
        downgrade(engine, "0021")
        columns_after = {c["name"] for c in inspect(engine).get_columns("log_attachments")}
        assert "transient" not in columns_after
        with engine.connect() as connection:
            count = connection.execute(text("SELECT COUNT(*) FROM log_attachments")).scalar_one()
            assert count == 2
    finally:
        engine.dispose()
