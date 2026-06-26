"""Raw log-event ORM model (FTY-030).

``log_events`` is the user-owned record of a single natural-language log: the
raw text the user typed, its lifecycle :class:`~app.enums.LogEventStatus`, and
timestamps. It is the backend the mobile Today timeline (FTY-031) and polling
(FTY-032) read from, and the row the estimator pipeline (Milestone 4) later
drives through its remaining statuses.

The ``user_id`` foreign key with ``ON DELETE CASCADE`` is the persistence-layer
ownership boundary: a log event always belongs to exactly one user and is
removed when that account is deleted (retention: logs retained until user or
account deletion). ``raw_text`` is sensitive personal data and is never logged.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.enums import LogEventStatus
from app.models.identity import User


def _utcnow() -> datetime:
    """Timezone-aware UTC now, used for portable Python-side timestamp defaults."""

    return datetime.now(UTC)


class LogEvent(Base):
    """A single raw natural-language log entry, owned by exactly one user.

    ``raw_text`` holds the untrusted user input verbatim; ``status`` tracks the
    event through the state machine (see :mod:`app.services.log_events`).
    ``created_at`` anchors the event to a calendar day for the Today timeline;
    day-window resolution happens in the user's timezone at the service layer.
    """

    __tablename__ = "log_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=LogEventStatus.PENDING)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    user: Mapped[User] = relationship()
