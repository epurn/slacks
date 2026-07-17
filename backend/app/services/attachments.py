"""Attachment ingest service: discard-by-default retention + fail-closed upload limits (FTY-077).

Owns the one behaviour behind the ``log_attachments`` contract: turning an uploaded
image into either **nothing** (the default) or **exactly one** persisted row (an
explicit save), and rejecting anything that is not an acceptable image before it is
stored or handed onward.

Two guarantees, both fail-closed:

1. **Discard by default.** :func:`ingest_upload` persists no raw image unless the
   caller passes ``save=True``. The default path validates the upload (so the bytes
   are safe to hand to a downstream consumer such as extraction) and then returns
   ``None`` — no ``log_attachments`` row is written. Only an explicit save writes a
   single row.

2. **Upload constraints reject before storage.** Every upload is validated
   *before* any persistence: an oversized payload, a disallowed content-type, or
   bytes whose signature is not the declared image type are rejected
   deterministically (:class:`AttachmentTooLarge` / :class:`AttachmentInvalidContentType`).
   Validation runs on both the discard and the save path, so an invalid upload never
   reaches storage or a downstream consumer.

FTY-375 adds the **transient** retention class for the unified text+image log
submission (``docs/contracts/log-attachments.md`` v3): each validated image of a
mixed submission is persisted as a row marked ``transient`` — in the same
transaction as the event create, so the ids-only async worker can load it by
event id — and hard-deleted by :func:`purge_transient_for_event` when the event's
estimation reaches a terminal status, unless the submission chose ``save=true``
(written as ordinary saved rows instead). Discard-by-default is preserved: with
``save`` absent/false, no image survives estimation.

Object-level authorization fails closed: a caller may only save attachments under
their own ``user_id`` (:class:`AttachmentForbidden`). The stored bytes are untrusted
input — validated as data, never logged, never interpreted.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.models.attachments import LogAttachment
from app.models.identity import User
from app.schemas.attachments import ALLOWED_CONTENT_TYPES, MAX_ATTACHMENT_BYTES


class AttachmentError(Exception):
    """Base class for attachment ingest failures (all fail closed)."""


class AttachmentTooLarge(AttachmentError):
    """Raised when an upload exceeds :data:`MAX_ATTACHMENT_BYTES` (rejected before storage)."""


class AttachmentInvalidContentType(AttachmentError):
    """Raised when an upload is not an allowed image type or its bytes do not match it."""


class AttachmentForbidden(AttachmentError):
    """Raised when a caller saves an attachment they do not own (fails closed)."""


#: Leading byte signatures for each allowed image type. The declared content-type is
#: only trusted when the bytes actually start with the matching magic number, so a
#: non-image payload mislabelled as an image is rejected.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8\xff"
_WEBP_RIFF = b"RIFF"
_WEBP_FORMAT = b"WEBP"


def _detect_image_type(data: bytes) -> str | None:
    """Return the content-type implied by ``data``'s signature, or ``None``.

    Detection is by magic number only: it confirms the bytes are the image format
    they claim to be. It is a fail-closed gate, not a full decoder.
    """

    if data.startswith(_PNG_SIGNATURE):
        return "image/png"
    if data.startswith(_JPEG_SIGNATURE):
        return "image/jpeg"
    # WEBP is a RIFF container: "RIFF" <4-byte size> "WEBP".
    if data[:4] == _WEBP_RIFF and data[8:12] == _WEBP_FORMAT:
        return "image/webp"
    return None


def _normalize_content_type(content_type: str) -> str:
    """Lower-case the media type and drop any parameters (e.g. ``; charset=...``)."""

    return content_type.split(";", 1)[0].strip().lower()


def validate_upload(data: bytes, content_type: str) -> str:
    """Validate an upload fail-closed and return the canonical image content-type.

    Checks, in order, all *before* any storage:

    1. size is within :data:`MAX_ATTACHMENT_BYTES` (else :class:`AttachmentTooLarge`);
    2. the declared content-type is in :data:`ALLOWED_CONTENT_TYPES`;
    3. the bytes' signature matches that declared type.

    A failure on (2) or (3) raises :class:`AttachmentInvalidContentType`. The
    returned canonical type is what gets persisted, never the raw client string.
    """

    if len(data) > MAX_ATTACHMENT_BYTES:
        raise AttachmentTooLarge(
            f"attachment is {len(data)} bytes; limit is {MAX_ATTACHMENT_BYTES}"
        )

    declared = _normalize_content_type(content_type)
    if declared not in ALLOWED_CONTENT_TYPES:
        raise AttachmentInvalidContentType(
            f"content-type {declared!r} is not an allowed image type"
        )

    detected = _detect_image_type(data)
    if detected != declared:
        # Empty/truncated/mislabelled bytes (detected is None or a different type)
        # are not the image they claim to be.
        raise AttachmentInvalidContentType(
            "upload bytes are not a valid image of the declared type"
        )

    return declared


def ingest_upload(
    session: Session,
    *,
    owner_id: uuid.UUID,
    current_user: User,
    log_event_id: uuid.UUID,
    data: bytes,
    content_type: str,
    save: bool = False,
) -> LogAttachment | None:
    """Validate an uploaded image and persist it **only** when ``save`` is true.

    Always authorizes the caller and validates the upload first, fail-closed, so an
    unauthorized or invalid upload never reaches storage. With ``save=False`` (the
    default, discard-by-default retention) returns ``None`` and writes no row. With
    ``save=True`` writes exactly one :class:`~app.models.attachments.LogAttachment`
    row owned by ``owner_id`` and returns it.
    """

    _authorize(owner_id, current_user)
    canonical_type = validate_upload(data, content_type)

    if not save:
        # Discard by default: the upload was validated (safe to hand onward) but no
        # raw image is persisted.
        return None

    attachment = LogAttachment(
        user_id=owner_id,
        log_event_id=log_event_id,
        content_type=canonical_type,
        byte_size=len(data),
        content_hash=hashlib.sha256(data).hexdigest(),
        data=data,
    )
    session.add(attachment)
    session.commit()
    session.refresh(attachment)
    return attachment


@dataclass(frozen=True)
class ValidatedImage:
    """An ``image`` part that already passed :func:`validate_upload` (FTY-375).

    ``content_type`` is the **canonical** allowlist value the validator returned,
    never the raw client string. Carrying validated parts as a distinct type keeps
    the persistence path unable to accept unvalidated bytes by construction.
    """

    data: bytes
    content_type: str


def stage_submission_images(
    session: Session,
    *,
    owner_id: uuid.UUID,
    current_user: User,
    log_event_id: uuid.UUID,
    images: Sequence[ValidatedImage],
    save: bool = False,
) -> list[LogAttachment]:
    """Stage a mixed submission's validated images as ``log_attachments`` rows.

    Adds one row per image to ``session`` **without committing** — the caller
    owns the transaction, so the rows commit atomically with the ``pending``
    event they belong to (``log-attachments.md`` v3: write at create, tied to
    the event; a rejected submission writes no row).

    Retention class is the submission-level ``save`` choice: ``save=False`` (the
    default) writes ``transient=True`` rows that live only for the estimation
    window and are hard-deleted by :func:`purge_transient_for_event` at the
    event's terminal status; ``save=True`` writes ordinary durable saved rows
    (``transient=False``) the purge never touches.

    Authorization fails closed like :func:`ingest_upload`: a cross-user call
    raises :class:`AttachmentForbidden` and stages nothing.
    """

    _authorize(owner_id, current_user)
    rows = [
        LogAttachment(
            user_id=owner_id,
            log_event_id=log_event_id,
            content_type=image.content_type,
            byte_size=len(image.data),
            content_hash=hashlib.sha256(image.data).hexdigest(),
            data=image.data,
            transient=not save,
        )
        for image in images
    ]
    session.add_all(rows)
    return rows


def purge_transient_for_event(session: Session, log_event_id: uuid.UUID) -> int:
    """Hard-delete an event's transient, unsaved attachment rows (FTY-375).

    The one sanctioned application-level row deletion (``log-attachments.md`` v3,
    ``docs/security/data-retention.md``): a ``transient=True`` row is a working
    buffer for the estimation window, not audit history. Deletes bytes and all —
    saved rows (``transient=False``, whether an explicit FTY-077/FTY-306 save or
    a mixed submission's ``save=true`` promotion) are never touched.

    Does **not** commit: the worker (FTY-376) calls this in the same transaction
    as the event's terminal status write, so the purge is atomic with the
    outcome — no purge job, no orphaned window. Returns the number of rows
    deleted (idempotent: a second call finds nothing and returns 0).
    """

    # ``Session.execute`` is typed as the base ``Result``; a DML statement always
    # returns a ``CursorResult``, which carries the matched-row count.
    result = cast(
        "CursorResult[Any]",
        session.execute(
            delete(LogAttachment).where(
                LogAttachment.log_event_id == log_event_id,
                LogAttachment.transient.is_(True),
            )
        ),
    )
    return int(result.rowcount)


def _authorize(owner_id: uuid.UUID, current_user: User) -> None:
    """Fail closed unless ``current_user`` owns ``owner_id``'s attachments."""

    if owner_id != current_user.id:
        raise AttachmentForbidden("cross-user attachment access denied")
