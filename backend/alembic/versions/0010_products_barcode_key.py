"""products.barcode key for the Open Food Facts source

Adds the additive barcode key the Open Food Facts source needs (FTY-060):

- ``products`` gains a nullable ``barcode`` column plus an index
  (``ix_products_barcode``). For a barcode-sourced row (``source =
  open_food_facts``) it holds the normalized UPC/EAN the resolver looks up by; it is
  ``NULL`` for a name-keyed generic (USDA FDC) row. The existing ``(source,
  query_key)`` uniqueness still dedupes one cache row per product (OFF rows store the
  normalized barcode in ``query_key`` as well).

Additive: a single nullable column + index on an existing table; no prior column is
altered and no backfill is needed (existing FDC rows keep ``barcode = NULL``). The
``products`` table stays a **global** cache with no user-specific data
(``docs/security/data-retention.md``).

Rollback: ``alembic downgrade 0009`` (or ``-1``) drops the index then the column,
fully reversing this migration.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-27
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("products", sa.Column("barcode", sa.String(length=32), nullable=True))
    op.create_index("ix_products_barcode", "products", ["barcode"])


def downgrade() -> None:
    op.drop_index("ix_products_barcode", table_name="products")
    op.drop_column("products", "barcode")
