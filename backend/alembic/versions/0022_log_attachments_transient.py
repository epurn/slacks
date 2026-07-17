"""log_attachments transient retention marker (FTY-375)

Adds the ``transient`` boolean pinned by ``docs/contracts/log-attachments.md``
v3 (FTY-374): a ``log_attachments`` row written for a unified text+image log
submission is persisted only for the estimation window (``transient = true``)
and hard-deleted at the event's terminal estimation status unless the
submission chose ``save=true`` (written as an ordinary ``transient = false``
saved row).

Additive and reversible; no backfill semantics beyond the default: every
existing row — the FTY-077 / FTY-306 explicit-save flows — keeps
``transient = false`` and is unaffected. The server default is ``sa.false()``
so the rendered DDL is valid on both SQLite and Postgres (the FTY-143 lesson:
``BOOLEAN DEFAULT 0`` is SQLite-only).

Rollback: ``alembic downgrade 0021`` (or ``-1``) drops the column.

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "log_attachments",
        sa.Column("transient", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    with op.batch_alter_table("log_attachments") as batch_op:
        batch_op.drop_column("transient")
