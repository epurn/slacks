"""saved_foods + food_aliases tables

Adds the saved-foods + aliases foundation (FTY-052):

- ``saved_foods`` — one user-owned row per deliberately-saved food: the canonical
  ``name`` plus a ``name_normalized`` form for matching, the corrected nutrition
  snapshot (``calories`` non-null; ``protein_g`` / ``carbs_g`` / ``fat_g``
  nullable), a default ``serving_size`` + ``serving_unit``, and a ``source``
  provenance field (v1: saved-from-correction). ``user_id`` is
  ``ON DELETE CASCADE``.
- ``food_aliases`` — the original typed phrase mapped to a saved food: ``alias``
  plus ``alias_normalized`` for matching, a ``user_id`` FK and a ``saved_food_id``
  FK, both ``ON DELETE CASCADE`` so aliases are removed with their user and with
  their parent saved food.

The ``*_normalized`` columns are indexed for the typeahead's prefix/contains
lookups, alongside the ``user_id`` ownership indexes.

Additive: two new tables; no prior table is altered.

Rollback: ``alembic downgrade 0008`` (or ``-1``) drops ``food_aliases`` then
``saved_foods`` and their indexes, fully reversing this migration.

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_foods",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("name_normalized", sa.String(length=200), nullable=False),
        sa.Column("calories", sa.Float(), nullable=False),
        sa.Column("protein_g", sa.Float(), nullable=True),
        sa.Column("carbs_g", sa.Float(), nullable=True),
        sa.Column("fat_g", sa.Float(), nullable=True),
        sa.Column("serving_size", sa.Float(), nullable=False),
        sa.Column("serving_unit", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_saved_foods_user_id", "saved_foods", ["user_id"])
    op.create_index("ix_saved_foods_name_normalized", "saved_foods", ["name_normalized"])

    op.create_table(
        "food_aliases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("saved_food_id", sa.Uuid(), nullable=False),
        sa.Column("alias", sa.String(length=200), nullable=False),
        sa.Column("alias_normalized", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["saved_food_id"], ["saved_foods.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_food_aliases_user_id", "food_aliases", ["user_id"])
    op.create_index("ix_food_aliases_saved_food_id", "food_aliases", ["saved_food_id"])
    op.create_index("ix_food_aliases_alias_normalized", "food_aliases", ["alias_normalized"])


def downgrade() -> None:
    op.drop_index("ix_food_aliases_alias_normalized", table_name="food_aliases")
    op.drop_index("ix_food_aliases_saved_food_id", table_name="food_aliases")
    op.drop_index("ix_food_aliases_user_id", table_name="food_aliases")
    op.drop_table("food_aliases")

    op.drop_index("ix_saved_foods_name_normalized", table_name="saved_foods")
    op.drop_index("ix_saved_foods_user_id", table_name="saved_foods")
    op.drop_table("saved_foods")
