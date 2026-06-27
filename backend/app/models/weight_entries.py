"""Weight-entry ORM model (FTY-070).

``weight_entries`` is the user-owned time series of body-weight readings.
It is intentionally separate from the ``user_profiles.weight_kg`` current-weight
snapshot: this table records dated historical observations so the mobile
weight-trend chart (FTY-074) can query entries over a date range.

``weight_kg`` is always the canonical kilograms value; input-unit conversion
(lb → kg for ``imperial`` users) happens in the service layer before
persistence. ``effective_date`` is the calendar day the reading applies to
(indexed for range queries); ``created_at`` is the audit timestamp of the row.

The ``user_id`` foreign key with ``ON DELETE CASCADE`` is the persistence-layer
ownership boundary: an entry always belongs to exactly one user and is removed
when that account is deleted (retention: weight entries retained until user or
account deletion). Weight values are sensitive personal data and must never
be logged.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.identity import User


def _utcnow() -> datetime:
    """Timezone-aware UTC now, used for portable Python-side timestamp defaults."""

    return datetime.now(UTC)


class WeightEntry(Base):
    """A single dated body-weight observation, owned by exactly one user.

    ``weight_kg`` is the canonical kilograms value; the converting caller must
    have already applied lb → kg for imperial users. ``effective_date`` is the
    calendar date the reading applies to, distinct from the audit ``created_at``
    timestamp so the chart can plot readings against the day the user recorded
    them, not the day the row was written.
    """

    __tablename__ = "weight_entries"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    user: Mapped[User] = relationship()
