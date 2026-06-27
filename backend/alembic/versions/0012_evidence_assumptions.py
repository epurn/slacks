"""evidence_sources.assumptions

Adds the nullable ``assumptions`` column to ``evidence_sources`` (FTY-062): a JSON
array of the documented assumptions behind a resolution — most importantly the
**model-prior fallback reason** recorded when a named product could not be costed
from an official source, so the entry surfaces an explicit source status and stays
user-editable (``docs/contracts/evidence-retrieval.md`` Evidence Source Record;
``docs/security/data-retention.md``). It never stores raw user text or page content.

Additive: one new nullable column; existing USDA/OFF/label evidence rows keep
``assumptions = NULL`` and no backfill is needed. No prior column is altered.

Rollback: ``alembic downgrade 0011`` (or ``-1``) drops the column, fully reversing
this migration, verified by an apply/rollback test against a throwaway database.

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "evidence_sources",
        sa.Column("assumptions", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evidence_sources", "assumptions")
