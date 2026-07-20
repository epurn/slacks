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

from sqlalchemy import ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UtcDateTime
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
    #: Short, human-readable meal label (FTY-421), e.g. ``"Turkey sandwich"``.
    #: **Model-generated, never user-authored** in v1: the estimator (FTY-422) is
    #: the sole writer, so this is ``NULL`` on every existing row and on every
    #: freshly-created event until estimation names it. It is derived user data —
    #: a label over what the user logged — so it is treated like other event
    #: content: returned to the owner, but kept out of logs/errors alongside
    #: ``raw_text``.
    name: Mapped[str | None] = mapped_column(String(200), nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=LogEventStatus.PENDING)
    #: Opaque client-supplied idempotency token (FTY-096): a UUID/ULID by
    #: convention, never parsed by the server. ``NULL`` for the online/no-key and
    #: label-upload paths, which therefore insert freely (NULL keys are distinct
    #: under the composite unique index). A non-null key is unique per user, so a
    #: safe-to-retry offline submit converges on a single event.
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=_utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )
    #: Soft-void marker (FTY-321). ``NULL`` for a live event; set **once** to the
    #: void instant when the user deletes the entry. A voided event — and every
    #: derived item, correction, and evidence row hanging off it — is **retained**
    #: (the append-only audit/provenance stance is preserved), but the event is
    #: excluded from every read model and from the daily-summary totals, so it
    #: disappears from the day. Void is terminal: there is no un-void.
    voided_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True, default=None)

    user: Mapped[User] = relationship()

    #: Per-user idempotency namespace. The composite unique index is the dedup
    #: authority: two concurrent same-key submits collide here and the loser
    #: re-reads the committed sibling. Postgres/SQLite treat NULL keys as
    #: distinct, so unkeyed creates are never blocked.
    __table_args__ = (
        Index(
            "uq_log_events_user_idempotency_key",
            "user_id",
            "idempotency_key",
            unique=True,
        ),
    )
