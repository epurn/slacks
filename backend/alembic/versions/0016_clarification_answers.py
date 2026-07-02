"""clarification_answers

Adds the answer-persistence table for the clarify answer round-trip (FTY-171,
``docs/contracts/log-events.md`` v4 — Answer persistence):

- ``clarification_answers`` — at most one row per answered clarification
  question. ``question_id`` is **unique** (the idempotency anchor: a re-sent or
  concurrent duplicate answer collides here and converges to the stored row).
  ``log_event_id`` and ``user_id`` carry object-level ownership at the
  persistence boundary, and all three foreign keys cascade so retention follows
  the owning question, event, and account
  (``docs/security/data-retention.md``).

``answer_text`` is sensitive user data (tied to the user's log, like
``raw_text``): it is stored as data via parameterized inserts, returned only to
the owner, and never logged or copied into estimation-run ``trace``/``error``.

Additive: one new table; no prior table or column is altered and no backfill is
needed.

Rollback: ``alembic downgrade 0015`` (or ``-1``) drops the table and its
indexes, fully reversing this migration.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clarification_answers",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("question_id", sa.Uuid(), nullable=False),
        sa.Column("log_event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("answer_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id"], ["clarification_questions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["log_event_id"], ["log_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("question_id", name="uq_clarification_answers_question_id"),
    )
    op.create_index(
        "ix_clarification_answers_question_id", "clarification_answers", ["question_id"]
    )
    op.create_index(
        "ix_clarification_answers_log_event_id", "clarification_answers", ["log_event_id"]
    )
    op.create_index("ix_clarification_answers_user_id", "clarification_answers", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_clarification_answers_user_id", table_name="clarification_answers")
    op.drop_index("ix_clarification_answers_log_event_id", table_name="clarification_answers")
    op.drop_index("ix_clarification_answers_question_id", table_name="clarification_answers")
    op.drop_table("clarification_answers")
