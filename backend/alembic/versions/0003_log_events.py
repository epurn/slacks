"""log_events

Adds the log-event table (FTY-030): a user-owned record holding the raw
natural-language text the user logged, its lifecycle status, and timestamps. It
is the backend the mobile Today timeline (FTY-031) and polling (FTY-032) read
from. The ``user_id`` foreign key uses ``ON DELETE CASCADE`` so a user's log
events are removed when the account is deleted (retention: logs retained until
user or account deletion). ``created_at`` is indexed because the Today timeline
queries events by day.

Rollback: ``alembic downgrade 0002`` (or ``-1``) drops the table and its
indexes, fully reversing this migration.

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "log_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_log_events_user_id", "log_events", ["user_id"])
    op.create_index("ix_log_events_created_at", "log_events", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_log_events_created_at", table_name="log_events")
    op.drop_index("ix_log_events_user_id", table_name="log_events")
    op.drop_table("log_events")
