"""log_event soft-void marker

Adds the soft-void capability for a food log entry (FTY-321):

- ``log_events`` gains a nullable ``voided_at`` timestamptz. ``NULL`` for a live
  event; set **once** to the void instant when the user deletes the entry
  (``DELETE /api/users/{user_id}/log-events/{event_id}``). A voided event — and
  every derived item, correction, and evidence row hanging off it — is
  **retained** so the append-only audit/provenance stance is preserved; the
  event is instead **excluded** from every read model (log-event list / by-date /
  single GET, the clarification read/answer, the day-listing items) and from the
  daily-summary totals, so a mislogged entry disappears from the day without a
  hard row deletion. Void is a terminal status (no un-void).

Additive: a single nullable column on an existing table; no prior column is
altered and no backfill is needed (existing rows keep ``voided_at = NULL`` and
stay live). Retention is unchanged — the column lives on ``log_events`` and is
removed by the existing ``ON DELETE CASCADE`` on account deletion
(``docs/security/data-retention.md``).

Rollback: ``alembic downgrade 0018`` (or ``-1``) drops the column, fully
reversing this migration. A fresh rollback has no bearing on the append-only
guards (voiding never deleted a row).

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "log_events",
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("log_events", "voided_at")
