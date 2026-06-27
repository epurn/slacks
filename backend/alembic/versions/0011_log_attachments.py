"""log_attachments

Adds the ``log_attachments`` table (FTY-077): a user-owned record holding a saved
image **only when the user explicitly saves it**. It is the storage + retention
foundation for nutrition-label extraction (FTY-061) and resolves the
``log-events.md`` "excluded: ``log_attachments`` (FTY-060/061)" placeholder. The
table never stores model output — that is evidence (``evidence_sources``).

Retention is discard-by-default (``docs/security/data-retention.md``): the default
upload flow persists no row; only an explicit save writes one. Both ``user_id`` and
``log_event_id`` use ``ON DELETE CASCADE`` so a saved attachment is removed with its
owning log event, user, or account. The row carries the metadata needed to retrieve
and delete the saved image (content-type, byte size, content hash) alongside the
image bytes.

Additive: one new table; no prior table is altered.

Rollback: ``alembic downgrade 0010`` (or ``-1``) drops the table and its indexes,
fully reversing this migration.

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "log_attachments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("log_event_id", sa.Uuid(), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["log_event_id"], ["log_events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_log_attachments_user_id", "log_attachments", ["user_id"])
    op.create_index("ix_log_attachments_log_event_id", "log_attachments", ["log_event_id"])


def downgrade() -> None:
    op.drop_index("ix_log_attachments_log_event_id", table_name="log_attachments")
    op.drop_index("ix_log_attachments_user_id", table_name="log_attachments")
    op.drop_table("log_attachments")
