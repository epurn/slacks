"""corrections value-type-polymorphic audit (FTY-377)

Generalizes the ``corrections`` audit so it can record a **text-valued** field
change — the ``name_edit`` display-name rename — not only a numeric one:

- ``new_value`` becomes **nullable** (a text correction has no numeric value);
- adds nullable ``old_value_text`` / ``new_value_text`` (``VARCHAR(200)``,
  matching the derived-item ``name`` cap) carrying the prior/new display name;
- adds the ``ck_corrections_one_value_kind`` check constraint: exactly one of
  ``new_value`` / ``new_value_text`` is non-null per row, so a numeric and a
  text correction are each well-formed and mutually exclusive.

The ``name_edit`` ``CorrectionSource`` value itself is additive over the existing
string ``source`` column — no schema change beyond the above. The append-only
ORM ``UPDATE``/``DELETE`` guards apply to the new row kind unchanged.

Rollback: ``alembic downgrade 0020`` (or ``-1``) drops the check constraint and
the text columns and restores ``new_value NOT NULL``. Pre-v1, no production
data: any text-valued (``name_edit``) rows are dev-only, so the downgrade
deletes them first to make the NOT-NULL restore safe on any engine.

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Matches the derived-item ``name`` column cap (``String(200)``); see
# ``app.models.corrections.CORRECTION_TEXT_MAX_LENGTH``.
_TEXT_LENGTH = 200


def upgrade() -> None:
    with op.batch_alter_table("corrections") as batch_op:
        batch_op.add_column(
            sa.Column("old_value_text", sa.String(length=_TEXT_LENGTH), nullable=True)
        )
        batch_op.add_column(
            sa.Column("new_value_text", sa.String(length=_TEXT_LENGTH), nullable=True)
        )
        batch_op.alter_column(
            "new_value",
            existing_type=sa.Float(),
            nullable=True,
            existing_nullable=False,
        )
        batch_op.create_check_constraint(
            "ck_corrections_one_value_kind",
            "(new_value IS NOT NULL) <> (new_value_text IS NOT NULL)",
        )


def downgrade() -> None:
    # Text-valued rows cannot survive the NOT-NULL restore. Pre-v1 they are
    # dev-only data, so removing them keeps the downgrade clean on any engine.
    op.execute("DELETE FROM corrections WHERE new_value IS NULL")
    with op.batch_alter_table("corrections") as batch_op:
        batch_op.drop_constraint("ck_corrections_one_value_kind", type_="check")
        batch_op.alter_column(
            "new_value",
            existing_type=sa.Float(),
            nullable=False,
            existing_nullable=True,
        )
        batch_op.drop_column("new_value_text")
        batch_op.drop_column("old_value_text")
