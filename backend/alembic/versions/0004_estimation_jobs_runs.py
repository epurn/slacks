"""estimation_jobs and estimation_runs

Adds the estimator async trust-boundary tables (FTY-040):

- ``estimation_jobs`` — one job per log event (unique ``log_event_id``: the
  idempotency anchor), with the worker status and bounded-retry counters.
- ``estimation_runs`` — one auditable record per attempt, holding the
  reproducibility metadata required by ``docs/security/data-retention.md``
  (model/provider, schema version, tool names, source refs, assumptions,
  validation errors) plus a sanitized trace and error.

Both carry ``user_id`` with ``ON DELETE CASCADE`` (object-level ownership) and
cascade from ``log_event_id`` so a deleted log event removes its job and runs.
``estimation_runs.job_id`` cascades from ``estimation_jobs``.

Rollback: ``alembic downgrade 0003`` (or ``-1``) drops both tables and their
indexes, fully reversing this migration. Additive: no prior table is altered.

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-26
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "estimation_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("log_event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["log_event_id"], ["log_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("log_event_id", name="uq_estimation_jobs_log_event_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_estimation_jobs_idempotency_key"),
    )
    op.create_index("ix_estimation_jobs_log_event_id", "estimation_jobs", ["log_event_id"])
    op.create_index("ix_estimation_jobs_user_id", "estimation_jobs", ["user_id"])

    op.create_table(
        "estimation_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("log_event_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("schema_version", sa.String(length=32), nullable=True),
        sa.Column("tool_names", sa.JSON(), nullable=False),
        sa.Column("source_refs", sa.JSON(), nullable=False),
        sa.Column("assumptions", sa.JSON(), nullable=False),
        sa.Column("validation_errors", sa.JSON(), nullable=False),
        sa.Column("trace", sa.JSON(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["estimation_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["log_event_id"], ["log_events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_estimation_runs_job_id", "estimation_runs", ["job_id"])
    op.create_index("ix_estimation_runs_log_event_id", "estimation_runs", ["log_event_id"])
    op.create_index("ix_estimation_runs_user_id", "estimation_runs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_estimation_runs_user_id", table_name="estimation_runs")
    op.drop_index("ix_estimation_runs_log_event_id", table_name="estimation_runs")
    op.drop_index("ix_estimation_runs_job_id", table_name="estimation_runs")
    op.drop_table("estimation_runs")

    op.drop_index("ix_estimation_jobs_user_id", table_name="estimation_jobs")
    op.drop_index("ix_estimation_jobs_log_event_id", table_name="estimation_jobs")
    op.drop_table("estimation_jobs")
