"""Append-only corrections audit model (FTY-051).

A ``corrections`` row is an **immutable** audit record of a single user override of
a derived food/exercise item's value. Editing an estimator value never silently
overwrites it: the edit endpoint snapshots the original into the item's
``*_estimated`` column and appends one correction row per changed field here.

The table is append-only at the application boundary. Two ORM event guards reject
any ``UPDATE`` or ``DELETE`` issued through a session, so application code cannot
tamper with the audit trail (proven by ``tests/test_corrections_immutability.py``).
Account/user deletion still removes a user's rows through the database-level
``ON DELETE CASCADE`` foreign key — that is a retention requirement, not an
application edit, so it is intentionally outside the guard.

Each row carries ``user_id`` (object-level ownership, ``ON DELETE CASCADE``) and a
single typed reference to the corrected item: exactly one of
``derived_food_item_id`` / ``derived_exercise_item_id`` is set, with ``item_type``
as the discriminator. ``old_value`` / ``new_value`` are stored in the derived
item's canonical units (kcal, grams, or servings); the sensitive personal values
are data only and are never written to logs.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    Float,
    ForeignKey,
    String,
    Uuid,
    event,
)
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from app.db import Base, UtcDateTime
from app.enums import CandidateType, CorrectionSource
from app.models.derived import DerivedExerciseItem, DerivedFoodItem


def _utcnow() -> datetime:
    """Timezone-aware UTC now, used for portable Python-side timestamp defaults."""

    return datetime.now(UTC)


class CorrectionImmutableError(Exception):
    """Raised when application code tries to ``UPDATE`` or ``DELETE`` a correction.

    The ``corrections`` table is an append-only audit log; mutating or removing a
    persisted row through the ORM is a programming error and is rejected so the
    audit trail cannot be tampered with at the application boundary.
    """


class Correction(Base):
    """One immutable audit row describing a single field change on a derived item."""

    __tablename__ = "corrections"
    __table_args__ = (
        # Exactly one typed item reference is set; the row always points at one
        # derived item of the declared ``item_type``.
        CheckConstraint(
            "(derived_food_item_id IS NOT NULL) <> (derived_exercise_item_id IS NOT NULL)",
            name="ck_corrections_one_item_reference",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Discriminator for the typed item reference (``food`` / ``exercise``).
    item_type: Mapped[str] = mapped_column(String(16), nullable=False)
    derived_food_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("derived_food_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    derived_exercise_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("derived_exercise_items.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    #: Name of the changed field (e.g. ``calories``, ``protein_g``, ``quantity``,
    #: ``active_calories``). Stored as data; validated against the editable set at
    #: the endpoint before a row is ever written.
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Prior value in canonical units; ``None`` only when the field had no value yet.
    old_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: New value in canonical units.
    new_value: Mapped[float] = mapped_column(Float, nullable=False)
    #: Origin of the change (:class:`~app.enums.CorrectionSource`); v1 is ``user_edit``.
    source: Mapped[str] = mapped_column(
        String(32), nullable=False, default=CorrectionSource.USER_EDIT
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=_utcnow)


def _reject_mutation(_mapper: Mapper[Correction], _connection: object, _target: Correction) -> None:
    """ORM guard: corrections are append-only, so reject any update or delete."""

    raise CorrectionImmutableError("corrections are append-only; UPDATE/DELETE is not permitted")


# Block mutation at the application (ORM) boundary. Inserts are allowed; only
# changing or removing a persisted correction is rejected.
event.listen(Correction, "before_update", _reject_mutation)
event.listen(Correction, "before_delete", _reject_mutation)


def correction_item_type(item: object) -> CandidateType:
    """Return the :class:`~app.enums.CandidateType` for a derived item instance."""

    if isinstance(item, DerivedFoodItem):
        return CandidateType.FOOD
    if isinstance(item, DerivedExerciseItem):
        return CandidateType.EXERCISE
    raise TypeError(f"unsupported derived item type: {type(item)!r}")
