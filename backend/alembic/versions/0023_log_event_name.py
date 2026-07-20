"""log_event model-generated meal label (FTY-421)

Adds the nullable ``name`` column to ``log_events``: a short, human-readable
meal label (e.g. ``"Turkey sandwich"``) that the estimator (FTY-422) later
generates. It is **model-generated, never user-authored** in v1 and ``NULL`` on
every existing row and on every freshly-created event until estimation names it
— this story only creates and exposes the field; nothing populates it yet.

Additive: a single nullable ``String`` column on an existing table; no prior
column is altered and no backfill is needed (existing rows read back
``name = NULL``). Rendered DDL is Postgres/SQLite-parity — a plain nullable
column with no default. Retention is unchanged: the column lives on
``log_events`` and is removed by the existing ``ON DELETE CASCADE`` on account
deletion (``docs/security/data-retention.md``).

Rollback: ``alembic downgrade 0022`` (or ``-1``) drops the column, fully
reversing this migration.

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "log_events",
        sa.Column("name", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table("log_events") as batch_op:
        batch_op.drop_column("name")
