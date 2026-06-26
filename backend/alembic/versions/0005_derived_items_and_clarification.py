"""derived_food_items, derived_exercise_items, clarification_questions

Adds the structured-parse output tables (FTY-042):

- ``derived_food_items`` / ``derived_exercise_items`` — one row per parsed
  candidate, persisted **unresolved** (no calories; FTY-043/044 resolve them).
- ``clarification_questions`` — one row per question raised when a log event is
  too ambiguous to parse; persisted unanswered (the answer flow is a later story).

All three carry ``user_id`` and ``log_event_id`` with ``ON DELETE CASCADE``
(object-level ownership; retention follows the owning log event). Additive: no
prior table is altered.

Rollback: ``alembic downgrade 0004`` (or ``-1``) drops the three tables and their
indexes, fully reversing this migration.

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _create_derived_item_table(name: str) -> None:
    """Create a derived food/exercise candidate table (identical shape)."""

    op.create_table(
        name,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("log_event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("quantity_text", sa.String(length=120), nullable=False),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("amount", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["log_event_id"], ["log_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(f"ix_{name}_log_event_id", name, ["log_event_id"])
    op.create_index(f"ix_{name}_user_id", name, ["user_id"])


def _drop_derived_item_table(name: str) -> None:
    op.drop_index(f"ix_{name}_user_id", table_name=name)
    op.drop_index(f"ix_{name}_log_event_id", table_name=name)
    op.drop_table(name)


def upgrade() -> None:
    _create_derived_item_table("derived_food_items")
    _create_derived_item_table("derived_exercise_items")

    op.create_table(
        "clarification_questions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("log_event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["log_event_id"], ["log_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_clarification_questions_log_event_id",
        "clarification_questions",
        ["log_event_id"],
    )
    op.create_index(
        "ix_clarification_questions_user_id",
        "clarification_questions",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_clarification_questions_user_id", table_name="clarification_questions")
    op.drop_index("ix_clarification_questions_log_event_id", table_name="clarification_questions")
    op.drop_table("clarification_questions")

    _drop_derived_item_table("derived_exercise_items")
    _drop_derived_item_table("derived_food_items")
