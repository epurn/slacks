"""Log-attachment ORM model (FTY-077).

``log_attachments`` is a user-owned table that holds an uploaded image **only when
the user explicitly saves it**. It is the storage + retention foundation for
nutrition-label extraction (FTY-061); it carries no extraction logic and never
stores model output (that is evidence, ``evidence_sources``).

Retention is **discard by default** (``docs/security/data-retention.md``): an
uploaded image is kept only while needed and discarded afterwards unless the user
explicitly saves the attachment. The default flow persists no raw image; an
explicit save writes exactly one row here. FTY-374/FTY-375 add a second,
**transient** retention class (``transient = true``): a unified text+image
submission's images are persisted only for the estimation window so the ids-only
async worker can load them by event id, then hard-deleted at the event's terminal
estimation status unless the submission chose ``save=true``. The retention
behaviour itself lives in :mod:`app.services.attachments` — this model is just the
persisted shape of a stored image.

Both ``user_id`` and ``log_event_id`` are foreign keys with ``ON DELETE CASCADE``
so a saved attachment is object-level owned and removed with its owning log event,
user, or account — the same ownership boundary the derived items use. The row
carries the metadata needed to retrieve and delete the saved image (its
content-type, byte size, and content hash) alongside the image bytes themselves.
The stored bytes are untrusted user input: schema/size/content-type validated at
the service boundary before they are ever persisted, and never logged.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, ForeignKey, Integer, LargeBinary, String, Uuid, false
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base, UtcDateTime


def _utcnow() -> datetime:
    """Timezone-aware UTC now, used for portable Python-side timestamp defaults."""

    return datetime.now(UTC)


class LogAttachment(Base):
    """A user-owned saved image attached to a log event.

    A row exists only when the user explicitly saved the attachment; the default
    upload flow persists nothing. ``data`` holds the raw image bytes, and
    ``content_type`` / ``byte_size`` / ``content_hash`` are the metadata needed to
    serve and delete the saved image on user request.
    """

    __tablename__ = "log_attachments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    log_event_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("log_events.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: Validated image content-type the bytes were accepted as (e.g. ``image/jpeg``).
    #: One of the service allowlist; never a client-controlled free string at rest.
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    #: Size of :attr:`data` in bytes, recorded so the saved image can be described
    #: without reading the blob.
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    #: SHA-256 hex digest of :attr:`data` (64 chars) for integrity/dedup checks.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    #: The saved image bytes. Untrusted input, size- and content-type-validated at
    #: the service boundary before storage; never logged.
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    #: Transient retention marker (FTY-374/FTY-375, ``log-attachments.md`` v3).
    #: ``True`` marks a mixed-submission image persisted only for the estimation
    #: window: the worker hard-deletes it in the same transaction as the event's
    #: terminal estimation status (:func:`app.services.attachments.purge_transient_for_event`).
    #: ``False`` (the default) is an ordinary durable saved row — the FTY-077 /
    #: FTY-306 explicit saves and a mixed submission's ``save=true`` promotion —
    #: never touched by the purge.
    transient: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )
