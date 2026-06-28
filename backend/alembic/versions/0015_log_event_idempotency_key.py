"""log_event idempotency key

Adds the optional client-supplied idempotency key for safe-to-retry offline
submit (FTY-096):

- ``log_events`` gains a nullable ``idempotency_key`` column — an opaque client
  token (a UUID/ULID by convention) the server stores but never parses. It is
  ``NULL`` for the online/no-key create path and the label-upload path, which
  keep inserting freely.
- A composite **unique index** ``uq_log_events_user_idempotency_key`` on
  ``(user_id, idempotency_key)`` makes the key namespace per-user and the
  database the dedup authority: two concurrent same-key submits collide here so
  exactly one event is created. Postgres (and SQLite) treat ``NULL`` keys as
  distinct, so unkeyed rows — existing and new — are unaffected.

Additive: a single nullable column + unique index on an existing table; no prior
column is altered and no backfill is needed (existing rows keep
``idempotency_key = NULL``). Retention is unchanged — the column lives on
``log_events`` and is removed by the existing ``ON DELETE CASCADE`` on account
deletion (``docs/security/data-retention.md``).

Rollback: ``alembic downgrade 0014`` (or ``-1``) drops the index then the
column, fully reversing this migration.

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "log_events",
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
    )
    op.create_index(
        "uq_log_events_user_idempotency_key",
        "log_events",
        ["user_id", "idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_log_events_user_idempotency_key", table_name="log_events")
    op.drop_column("log_events", "idempotency_key")
