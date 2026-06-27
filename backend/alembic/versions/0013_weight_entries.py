"""weight_entries

Adds the ``weight_entries`` table (FTY-070): a user-owned time series of body-weight
entries, distinct from the single current ``weight_kg`` snapshot on ``user_profiles``.
Each row stores a canonical kg weight and an effective date — the calendar day the
weight was recorded for — so the mobile weight-trend chart (FTY-074) can query
entries by date range.

``user_id`` uses ``ON DELETE CASCADE`` so a user's weight entries are removed when the
account is deleted. ``effective_date`` is indexed because the chart queries by date range;
``user_id`` is indexed because all access paths filter by owner.

Rollback: ``alembic downgrade 0012`` (or ``-1``) drops the table and its indexes,
fully reversing this migration.

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weight_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("weight_kg", sa.Float(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_weight_entries_user_id", "weight_entries", ["user_id"])
    op.create_index("ix_weight_entries_effective_date", "weight_entries", ["effective_date"])


def downgrade() -> None:
    op.drop_index("ix_weight_entries_effective_date", table_name="weight_entries")
    op.drop_index("ix_weight_entries_user_id", table_name="weight_entries")
    op.drop_table("weight_entries")
