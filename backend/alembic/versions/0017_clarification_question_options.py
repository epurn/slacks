"""clarification question options

Adds the FTY-170/172 quick-pick option carrier to persisted clarification
questions. Existing deterministic backend-generated questions backfill to the
empty option list; the parse producer writes 2-5 options for model-raised
clarification questions.

Question text and options are sensitive user-tied log data. They are stored as
bounded JSON data via parameterized ORM writes, never logged, and never treated
as executable instructions.

Rollback: ``alembic downgrade 0016`` (or ``-1``) drops the column, fully
reversing this migration.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clarification_questions",
        sa.Column("options", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    op.drop_column("clarification_questions", "options")
