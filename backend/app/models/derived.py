"""Derived candidate and clarification-question ORM models (FTY-042).

The structured parse step turns a log event's raw text into three kinds of
user-owned rows:

- ``derived_food_items`` / ``derived_exercise_items`` — one row per extracted
  candidate, persisted **unresolved** (``status = unresolved``, no calories). The
  calculation steps (FTY-043/044) later attach energy/macros and mark them
  ``resolved``; FTY-042 only writes the parsed shape (name, raw portion phrase,
  and an optional best-effort unit/amount).
- ``clarification_questions`` — one row per question when the parse is too
  ambiguous to commit to candidates. The event goes ``needs_clarification`` and
  the questions persist *unanswered*; the answer flow, table, and UI are a later
  story.

Every table carries ``log_event_id`` and ``user_id`` foreign keys with
``ON DELETE CASCADE`` so the rows are object-level owned and removed with their
log event, user, or account (retention follows the owning log event, per
``docs/security/data-retention.md``). The model never executes or trusts the text
it stores: candidate names and questions are schema-validated data written
through parameterized ORM inserts, never instructions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.enums import DerivedItemStatus


def _utcnow() -> datetime:
    """Timezone-aware UTC now, used for portable Python-side timestamp defaults."""

    return datetime.now(UTC)


class _DerivedItem(Base):
    """Shared columns for an unresolved derived food/exercise candidate.

    Abstract base: the food and exercise candidates have identical shape but live
    in separate tables so the ``type`` discriminator is the table itself and the
    later calculators can query each kind directly.
    """

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    log_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("log_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Display name of the extracted item (e.g. "rice"). Schema-validated, stored
    #: as data — never interpreted as an instruction.
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    #: Raw portion phrase as written ("two", "150g", "a bowl").
    quantity_text: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    #: Optional best-effort normalisation; canonical resolution is FTY-043/044.
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    #: Resolution status; FTY-042 always writes ``unresolved`` (no calories yet).
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default=DerivedItemStatus.UNRESOLVED
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )


class DerivedFoodItem(_DerivedItem):
    """An unresolved food candidate parsed from a log event."""

    __tablename__ = "derived_food_items"


class DerivedExerciseItem(_DerivedItem):
    """An unresolved exercise candidate parsed from a log event."""

    __tablename__ = "derived_exercise_items"


class ClarificationQuestion(Base):
    """A question the parse step raised when a log event was too ambiguous.

    Persisted unanswered: FTY-042 stores the question and transitions the event to
    ``needs_clarification``. The answer flow, ``clarification_answers``, and UI are
    a later story. ``position`` preserves the order the questions were asked.
    """

    __tablename__ = "clarification_questions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    log_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("log_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
