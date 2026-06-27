"""Saved-food and alias ORM models (FTY-052).

A user can deliberately **save** a corrected food (from FTY-051) so the mobile
client can re-apply its stored nutrition later without re-estimating. Two
user-owned tables back that:

- ``saved_foods`` — one row per deliberately-saved food: the canonical name, a
  normalized name for matching, the corrected nutrition snapshot (calories,
  macros, and a default serving size + unit), and a ``source`` recording
  provenance (v1: saved-from-correction).
- ``food_aliases`` — the free-text phrase the user originally typed, mapped to a
  saved food. One save creates one alias; later searches match a query against
  both the saved food's name and any of its aliases.

Both tables carry ``user_id`` with ``ON DELETE CASCADE`` so they are object-level
owned and removed on user/account deletion (retention follows
``docs/security/data-retention.md``). ``food_aliases`` additionally cascades from
its ``saved_foods`` parent. The stored name, alias, and serving unit are
schema-validated free text written through parameterized ORM inserts — data only,
never interpreted as instructions, and never written to logs.

The ``*_normalized`` columns hold the output of :func:`app.normalization.normalize_text`
(case-folded, diacritic- and whitespace-normalized) so the typeahead matches on a
deterministic form; they are indexed for prefix/contains lookups.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.enums import SavedFoodSource


def _utcnow() -> datetime:
    """Timezone-aware UTC now, used for portable Python-side timestamp defaults."""

    return datetime.now(UTC)


class SavedFood(Base):
    """A user-owned, deliberately-saved food with its corrected nutrition snapshot."""

    __tablename__ = "saved_foods"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Canonical display name as saved (e.g. "white rice"). Schema-validated free
    #: text, stored as data — never interpreted as an instruction.
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Normalized form of :attr:`name` for deterministic prefix/contains matching
    #: (:func:`app.normalization.normalize_text`). Indexed for typeahead lookups.
    name_normalized: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    #: Corrected energy (kcal) for one default serving. Non-null: a save always
    #: carries a resolved calorie value.
    calories: Mapped[float] = mapped_column(Float, nullable=False)
    #: Corrected macros (grams) for one default serving; nullable because a
    #: corrected item may not have every macro resolved.
    protein_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    carbs_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    fat_g: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: The default serving the snapshot describes: ``serving_size`` of
    #: ``serving_unit`` (e.g. ``1`` ``serving``, ``150`` ``g``). The stored
    #: nutrition is for exactly this serving, so the client can re-apply it directly.
    serving_size: Mapped[float] = mapped_column(Float, nullable=False)
    serving_unit: Mapped[str] = mapped_column(String(32), nullable=False)
    #: Provenance (:class:`~app.enums.SavedFoodSource`); v1 is ``saved_from_correction``.
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default=SavedFoodSource.SAVED_FROM_CORRECTION
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class FoodAlias(Base):
    """The original typed phrase mapped to a saved food, owned by one user."""

    __tablename__ = "food_aliases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    saved_food_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("saved_foods.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: The free-text phrase the user originally typed (e.g. "my usual rice").
    #: Schema-validated data, stored verbatim, never logged.
    alias: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Normalized form of :attr:`alias` for deterministic prefix/contains matching.
    alias_normalized: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
