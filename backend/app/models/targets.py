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

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Integer, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UtcDateTime
from app.enums import TargetSource


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
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    daily_targets: Mapped[list[DailyTarget]] = relationship(
        back_populates="goal", cascade="all, delete-orphan"
    )


class DailyTarget(Base):
    """A daily calorie + macro target for a goal on a specific date.

    The **derived** columns (``daily_calorie_target_kcal``, the macro
    ``*_target_g`` columns, ``clamped`` / ``macros_clamped``, ``rmr_kcal`` /
    ``tdee_kcal``) are the deterministic FTY-022/FTY-094 calculator output and the
    source of truth for what a reset restores; ``inputs`` / ``assumptions`` hold
    the JSON snapshot that makes those numbers reproducible.

    The nullable ``override_*`` columns (FTY-095) carry an explicit user choice:
    each is ``NULL`` while the target is derived, and set to the user's value when
    they manually override it. The **effective** value a consumer measures against
    is the override when set, else the derived value — a pure read-time
    ``override ?? derived`` (see :attr:`effective_calorie_target_kcal` and the
    ``*_source`` helpers). A recompute updates the derived columns in place and
    leaves any in-force override untouched; an override is cleared only by an
    explicit reset or by deletion/replacement of the owning goal (``ON DELETE
    CASCADE`` from ``goal_id``).
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
    # --- Derived target columns (the calculator output; source of truth) -------
    daily_calorie_target_kcal: Mapped[int] = mapped_column(Integer, nullable=False)
    clamped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    protein_target_g: Mapped[int] = mapped_column(Integer, nullable=False)
    carbs_target_g: Mapped[int] = mapped_column(Integer, nullable=False)
    fat_target_g: Mapped[int] = mapped_column(Integer, nullable=False)
    macros_clamped: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    assumptions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # --- User-override columns (FTY-095; NULL when the target is derived) -------
    override_calorie_target_kcal: Mapped[int | None] = mapped_column(Integer, nullable=True)
    override_protein_target_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    override_carbs_target_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    override_fat_target_g: Mapped[int | None] = mapped_column(Integer, nullable=True)
    override_set_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=_utcnow)

    goal: Mapped[Goal] = relationship(back_populates="daily_targets")

    @property
    def effective_calorie_target_kcal(self) -> int:
        """The calorie target the app uses: the override when set, else derived."""

        if self.override_calorie_target_kcal is not None:
            return self.override_calorie_target_kcal
        return self.daily_calorie_target_kcal

    @property
    def effective_protein_target_g(self) -> int:
        """Effective protein target: override when set, else derived."""

        if self.override_protein_target_g is not None:
            return self.override_protein_target_g
        return self.protein_target_g

    @property
    def effective_carbs_target_g(self) -> int:
        """Effective carbohydrate target: override when set, else derived."""

        if self.override_carbs_target_g is not None:
            return self.override_carbs_target_g
        return self.carbs_target_g

    @property
    def effective_fat_target_g(self) -> int:
        """Effective fat target: override when set, else derived."""

        if self.override_fat_target_g is not None:
            return self.override_fat_target_g
        return self.fat_target_g

    @property
    def calorie_source(self) -> TargetSource:
        """``user`` when the calorie target is overridden, else ``derived``."""

        return _source(self.override_calorie_target_kcal)

    @property
    def protein_source(self) -> TargetSource:
        """``user`` when the protein target is overridden, else ``derived``."""

        return _source(self.override_protein_target_g)

    @property
    def carbs_source(self) -> TargetSource:
        """``user`` when the carbohydrate target is overridden, else ``derived``."""

        return _source(self.override_carbs_target_g)

    @property
    def fat_source(self) -> TargetSource:
        """``user`` when the fat target is overridden, else ``derived``."""

        return _source(self.override_fat_target_g)


def _source(override_value: int | None) -> TargetSource:
    """Map a nullable override column to its provenance flag."""

    return TargetSource.USER if override_value is not None else TargetSource.DERIVED
