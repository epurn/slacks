"""products, evidence_sources, derived_food_items resolution columns

Adds the generic-food resolution schema (FTY-044):

- ``products`` — a **global** cache of trusted-source per-100g nutrition facts. No
  ``user_id``: these are shared source facts, cached to avoid repeat external lookups.
  Unique on ``(source, query_key)``.
- ``evidence_sources`` — the **user-owned** provenance for one resolved food item
  (source ref, content hash, fetch timestamp, per-100g facts snapshot). Carries
  ``user_id`` and ``log_event_id`` with ``ON DELETE CASCADE``; ``product_id`` is
  ``ON DELETE SET NULL`` so clearing the global cache never deletes user evidence.
- ``derived_food_items`` gains nullable ``grams`` / ``calories`` / ``protein_g`` /
  ``carbs_g`` / ``fat_g`` — the canonical resolution output. Nullable: an
  ``unresolved`` candidate carries no calories.

Additive: no prior table is altered destructively. Global source facts (``products``)
are kept separate from user-owned evidence per ``docs/security/data-retention.md``.

Rollback: ``alembic downgrade 0006`` (or ``-1``) drops the two tables and the five
columns, fully reversing this migration.

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FOOD_RESOLUTION_COLUMNS = ("grams", "calories", "protein_g", "carbs_g", "fat_g")


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=128), nullable=False),
        sa.Column("query_key", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=False),
        sa.Column("calories_per_100g", sa.Float(), nullable=False),
        sa.Column("protein_per_100g", sa.Float(), nullable=False),
        sa.Column("carbs_per_100g", sa.Float(), nullable=False),
        sa.Column("fat_per_100g", sa.Float(), nullable=False),
        sa.Column("default_serving_g", sa.Float(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source", "query_key", name="uq_products_source_query"),
    )

    op.create_table(
        "evidence_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("log_event_id", sa.Uuid(), nullable=False),
        sa.Column("derived_food_item_id", sa.Uuid(), nullable=False),
        sa.Column("product_id", sa.Uuid(), nullable=True),
        sa.Column("source_type", sa.String(length=48), nullable=False),
        sa.Column("source_ref", sa.String(length=128), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calories_per_100g", sa.Float(), nullable=False),
        sa.Column("protein_per_100g", sa.Float(), nullable=False),
        sa.Column("carbs_per_100g", sa.Float(), nullable=False),
        sa.Column("fat_per_100g", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["log_event_id"], ["log_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["derived_food_item_id"], ["derived_food_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_sources_user_id", "evidence_sources", ["user_id"])
    op.create_index("ix_evidence_sources_log_event_id", "evidence_sources", ["log_event_id"])
    op.create_index(
        "ix_evidence_sources_derived_food_item_id",
        "evidence_sources",
        ["derived_food_item_id"],
    )
    op.create_index("ix_evidence_sources_product_id", "evidence_sources", ["product_id"])

    for column in _FOOD_RESOLUTION_COLUMNS:
        op.add_column("derived_food_items", sa.Column(column, sa.Float(), nullable=True))


def downgrade() -> None:
    for column in reversed(_FOOD_RESOLUTION_COLUMNS):
        op.drop_column("derived_food_items", column)

    op.drop_index("ix_evidence_sources_product_id", table_name="evidence_sources")
    op.drop_index("ix_evidence_sources_derived_food_item_id", table_name="evidence_sources")
    op.drop_index("ix_evidence_sources_log_event_id", table_name="evidence_sources")
    op.drop_index("ix_evidence_sources_user_id", table_name="evidence_sources")
    op.drop_table("evidence_sources")

    op.drop_table("products")
