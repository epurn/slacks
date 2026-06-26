"""derived_exercise_items.active_calories

Adds the costed-burn column for the MET exercise calculator (FTY-043):

- ``derived_exercise_items.active_calories`` — the net (``MET - 1``) active-calorie
  burn the calculator attaches when it resolves an exercise candidate. Nullable: an
  ``unresolved`` candidate (parsed but not yet costed) carries no calories.

Additive and reversible: only ``derived_exercise_items`` gains a nullable column, so
existing rows are unaffected and no backfill is needed.

Rollback: ``alembic downgrade 0005`` (or ``-1``) drops the column, fully reversing
this migration.

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "derived_exercise_items",
        sa.Column("active_calories", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("derived_exercise_items", "active_calories")
