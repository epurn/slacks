"""daily-target manual override + persisted derived macros

Extends ``daily_targets`` (FTY-095) so a single row carries both the derived
target and an explicit user override beside it:

- **Persisted derived macro columns** — ``protein_target_g`` / ``carbs_target_g``
  / ``fat_target_g`` / ``macros_clamped``. FTY-094 derives these in the calculator
  but did not persist them; persisting them here lets the read-model report the
  derived macro value (what a reset restores) straight from the row, mirroring the
  existing derived ``daily_calorie_target_kcal`` / ``clamped`` columns. Added
  ``NOT NULL`` with a type-correct server default (``0`` for the integer columns,
  ``false`` for the boolean ``macros_clamped``) so the ``ALTER`` is safe on any
  existing row; the application always writes the computed value.
- **Nullable user-override columns** — ``override_calorie_target_kcal`` and one
  per overridable macro (``override_protein_target_g`` / ``override_carbs_target_g``
  / ``override_fat_target_g``), each ``NULL`` when the target is derived, plus
  ``override_set_at`` (a bare timezone-aware timestamp; provenance/audit, no PII).

The effective value is a pure read-time ``override ?? derived``; the override
survives a derived recompute and is cleared only by an explicit reset or by the
existing ``ON DELETE CASCADE`` from ``goal_id`` (a deleted/replaced goal drops its
target and override together — no orphaned overrides).

Additive and fully reversible. Rollback (``alembic downgrade 0013`` / ``-1``)
drops exactly these columns, restoring the FTY-094 shape.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-28
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Persisted derived macro columns (FTY-094 derivation, now stored). NOT NULL
    # with a server default so the ALTER is safe; the app always writes the value.
    op.add_column(
        "daily_targets",
        sa.Column("protein_target_g", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "daily_targets",
        sa.Column("carbs_target_g", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "daily_targets",
        sa.Column("fat_target_g", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "daily_targets",
        sa.Column(
            "macros_clamped",
            sa.Boolean(),
            nullable=False,
            # Boolean-valued literal: Postgres rejects ``BOOLEAN DEFAULT 0``
            # (DatatypeMismatch) and accepts ``false``; SQLite tolerates both. An
            # integer literal here silently passed the SQLite-only gate but broke
            # every Postgres deploy (FTY-143).
            server_default=sa.text("false"),
        ),
    )

    # Nullable user-override columns (NULL while the target is derived).
    op.add_column(
        "daily_targets",
        sa.Column("override_calorie_target_kcal", sa.Integer(), nullable=True),
    )
    op.add_column(
        "daily_targets",
        sa.Column("override_protein_target_g", sa.Integer(), nullable=True),
    )
    op.add_column(
        "daily_targets",
        sa.Column("override_carbs_target_g", sa.Integer(), nullable=True),
    )
    op.add_column(
        "daily_targets",
        sa.Column("override_fat_target_g", sa.Integer(), nullable=True),
    )
    op.add_column(
        "daily_targets",
        sa.Column("override_set_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("daily_targets", "override_set_at")
    op.drop_column("daily_targets", "override_fat_target_g")
    op.drop_column("daily_targets", "override_carbs_target_g")
    op.drop_column("daily_targets", "override_protein_target_g")
    op.drop_column("daily_targets", "override_calorie_target_kcal")
    op.drop_column("daily_targets", "macros_clamped")
    op.drop_column("daily_targets", "fat_target_g")
    op.drop_column("daily_targets", "carbs_target_g")
    op.drop_column("daily_targets", "protein_target_g")
