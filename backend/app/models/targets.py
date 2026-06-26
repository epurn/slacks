"""Goal and derived-target ORM models (FTY-022).

Two user-owned tables:

- ``goals`` — a weight goal: the trajectory origin (``start_weight_kg`` /
  ``start_date``), the destination (``target_weight_kg`` / ``target_date``), and
  active state. The start snapshot is stored so the planned trajectory — and the
  daily target derived from it — is deterministic and does not drift as measured
  weight changes.
- ``daily_targets`` — a derived daily calorie target for a goal on a given date,
  with the full inputs/assumptions snapshot so the number is reproducible and
  explainable.

Both carry a ``user_id`` foreign key with ``ON DELETE CASCADE`` for object-level
ownership at the persistence boundary; ``daily_targets`` also cascades from its
``goal_id`` so deleting a goal removes its derived targets. Retention follows the
owning profile/goal: derived targets live until the goal is edited/replaced or
the account is deleted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> datetime:
    """Timezone-aware UTC now, used for portable Python-side timestamp defaults."""

    return datetime.now(UTC)


class Goal(Base):
    """A user's weight goal, owned by exactly one user."""

    __tablename__ = "goals"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    start_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_weight_kg: Mapped[float] = mapped_column(Float, nullable=False)
    target_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    daily_targets: Mapped[list[DailyTarget]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )


class DailyTarget(Base):
    """A derived daily calorie target for a goal on a specific date.

    ``rmr_kcal`` / ``tdee_kcal`` / ``daily_calorie_target_kcal`` are first-class
    queryable columns; ``inputs`` and ``assumptions`` hold the JSON snapshot that
    makes the number fully reproducible.
    """

    __tablename__ = "daily_targets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    goal_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("goals.id", ondelete="CASCADE"), nullable=False, index=True
    )
    for_date: Mapped[date] = mapped_column(Date, nullable=False)
    rmr_kcal: Mapped[float] = mapped_column(Float, nullable=False)
    tdee_kcal: Mapped[float] = mapped_column(Float, nullable=False)
    daily_calorie_target_kcal: Mapped[int] = mapped_column(Integer, nullable=False)
    clamped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    goal: Mapped[Goal] = relationship(back_populates="daily_targets")
