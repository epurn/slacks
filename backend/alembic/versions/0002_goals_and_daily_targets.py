"""goals and daily_targets

Adds the target-calculator tables (FTY-022): ``goals`` (a user's weight goal —
start/target weight and date plus active state) and ``daily_targets`` (a derived
daily calorie target with the inputs/assumptions snapshot). Both are user-owned
with ``ON DELETE CASCADE`` on ``user_id``; ``daily_targets`` also cascades from
``goal_id``.

Rollback: ``alembic downgrade 0001`` (or ``-1``) drops both tables in dependency
order, fully reversing this migration.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("start_weight_kg", sa.Float(), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("target_weight_kg", sa.Float(), nullable=False),
        sa.Column("target_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_goals_user_id", "goals", ["user_id"])

    op.create_table(
        "daily_targets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("goal_id", sa.Uuid(), nullable=False),
        sa.Column("for_date", sa.Date(), nullable=False),
        sa.Column("rmr_kcal", sa.Float(), nullable=False),
        sa.Column("tdee_kcal", sa.Float(), nullable=False),
        sa.Column("daily_calorie_target_kcal", sa.Integer(), nullable=False),
        sa.Column("clamped", sa.Boolean(), nullable=False),
        sa.Column("inputs", sa.JSON(), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["goal_id"], ["goals.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_daily_targets_user_id", "daily_targets", ["user_id"])
    op.create_index("ix_daily_targets_goal_id", "daily_targets", ["goal_id"])


def downgrade() -> None:
    op.drop_index("ix_daily_targets_goal_id", table_name="daily_targets")
    op.drop_index("ix_daily_targets_user_id", table_name="daily_targets")
    op.drop_table("daily_targets")
    op.drop_index("ix_goals_user_id", table_name="goals")
    op.drop_table("goals")
