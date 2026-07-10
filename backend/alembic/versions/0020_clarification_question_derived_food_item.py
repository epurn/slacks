"""clarification question item-scoped carrier

Adds the FTY-278 internal carrier for item-scoped partial clarification:
``clarification_questions.derived_food_item_id`` references the unresolved food
component the question owns. The link is nullable so existing event-level
questions remain valid, and uses ``ON DELETE SET NULL`` rather than cascade so
answered question history and its unique answer idempotency anchor are preserved
if a referenced item is ever removed.

The field is internal to the backend/estimator. It is not surfaced by the
clarification read DTO, which continues to expose the FTY-170
``id``/``text``/``options`` shape.

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("clarification_questions") as batch_op:
        batch_op.add_column(sa.Column("derived_food_item_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_clarification_questions_derived_food_item_id",
            "derived_food_items",
            ["derived_food_item_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_clarification_questions_derived_food_item_id",
            ["derived_food_item_id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("clarification_questions") as batch_op:
        batch_op.drop_index("ix_clarification_questions_derived_food_item_id")
        batch_op.drop_constraint(
            "fk_clarification_questions_derived_food_item_id",
            type_="foreignkey",
        )
        batch_op.drop_column("derived_food_item_id")
