"""baseline identity and profile model

Creates the foundational identity tables (FTY-020): ``users``,
``auth_identities``, and ``user_profiles``. Auth credentials live in
``auth_identities``, separate from ``users``; each user-owned table carries a
``user_id`` foreign key with ``ON DELETE CASCADE`` so account deletion removes
dependent rows.

Rollback: ``alembic downgrade base`` (or ``-1``) drops the three tables in
dependency order, fully reversing this migration.

Revision ID: 0001
Revises:
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "auth_identities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("identifier", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "identifier", name="uq_auth_provider_identifier"),
    )
    op.create_index("ix_auth_identities_user_id", "auth_identities", ["user_id"])

    op.create_table(
        "user_profiles",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("height_m", sa.Float(), nullable=True),
        sa.Column("weight_kg", sa.Float(), nullable=True),
        sa.Column("birth_year", sa.Integer(), nullable=True),
        sa.Column("metabolic_formula", sa.String(length=32), nullable=False),
        sa.Column("units_preference", sa.String(length=16), nullable=False),
        sa.Column("timezone", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # One profile per user: a unique index doubles as the ownership lookup index.
    op.create_index("ix_user_profiles_user_id", "user_profiles", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_user_profiles_user_id", table_name="user_profiles")
    op.drop_table("user_profiles")
    op.drop_index("ix_auth_identities_user_id", table_name="auth_identities")
    op.drop_table("auth_identities")
    op.drop_table("users")
