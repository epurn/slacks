"""corrections table + derived-item estimated/original snapshot columns

Adds the corrections-audit + edit foundation (FTY-051):

- ``derived_food_items`` gains nullable ``calories_estimated`` /
  ``protein_g_estimated`` / ``carbs_g_estimated`` / ``fat_g_estimated`` — the
  immutable snapshot of the estimator's original calories/macros, paired with the
  existing editable current columns (FTY-044).
- ``derived_exercise_items`` gains nullable ``active_calories_estimated`` — the
  snapshot of the original burn paired with the editable ``active_calories``
  (FTY-043).
- ``corrections`` — an append-only audit row per user override of a derived item
  field. Carries ``user_id`` and exactly one typed item reference
  (``derived_food_item_id`` / ``derived_exercise_item_id``), all
  ``ON DELETE CASCADE``; ``item_type`` discriminates the reference. Immutability is
  enforced at the application boundary (ORM guard) — the table is never updated or
  deleted by application code, only appended to.

Additive: existing rows gain nullable columns (snapshot-on-first-edit is the
backfill-free safety net), and no prior table is altered destructively.

Rollback: ``alembic downgrade 0007`` (or ``-1``) drops the ``corrections`` table
and the snapshot columns, fully reversing this migration.

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FOOD_SNAPSHOT_COLUMNS = (
    "calories_estimated",
    "protein_g_estimated",
    "carbs_g_estimated",
    "fat_g_estimated",
)
_EXERCISE_SNAPSHOT_COLUMN = "active_calories_estimated"


def upgrade() -> None:
    for column in _FOOD_SNAPSHOT_COLUMNS:
        op.add_column("derived_food_items", sa.Column(column, sa.Float(), nullable=True))
    op.add_column(
        "derived_exercise_items",
        sa.Column(_EXERCISE_SNAPSHOT_COLUMN, sa.Float(), nullable=True),
    )

    op.create_table(
        "corrections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("item_type", sa.String(length=16), nullable=False),
        sa.Column("derived_food_item_id", sa.Uuid(), nullable=True),
        sa.Column("derived_exercise_item_id", sa.Uuid(), nullable=True),
        sa.Column("field", sa.String(length=64), nullable=False),
        sa.Column("old_value", sa.Float(), nullable=True),
        sa.Column("new_value", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["derived_food_item_id"], ["derived_food_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["derived_exercise_item_id"], ["derived_exercise_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "(derived_food_item_id IS NOT NULL) <> (derived_exercise_item_id IS NOT NULL)",
            name="ck_corrections_one_item_reference",
        ),
    )
    op.create_index("ix_corrections_user_id", "corrections", ["user_id"])
    op.create_index("ix_corrections_derived_food_item_id", "corrections", ["derived_food_item_id"])
    op.create_index(
        "ix_corrections_derived_exercise_item_id",
        "corrections",
        ["derived_exercise_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_corrections_derived_exercise_item_id", table_name="corrections")
    op.drop_index("ix_corrections_derived_food_item_id", table_name="corrections")
    op.drop_index("ix_corrections_user_id", table_name="corrections")
    op.drop_table("corrections")

    op.drop_column("derived_exercise_items", _EXERCISE_SNAPSHOT_COLUMN)
    for column in reversed(_FOOD_SNAPSHOT_COLUMNS):
        op.drop_column("derived_food_items", column)
