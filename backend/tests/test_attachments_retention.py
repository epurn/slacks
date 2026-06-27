"""Discard-by-default retention + fail-closed upload constraints (FTY-077).

The security gate for this story, exercised at the service boundary against a
throwaway migrated SQLite database:

- **Retention default:** an upload with ``save=False`` writes **no** row and
  returns ``None`` — no raw image is persisted.
- **Explicit save:** an upload with ``save=True`` writes **exactly one** row with
  the expected metadata.
- **Negatives, fail-closed before storage:** an oversized payload, a disallowed
  content-type, and bytes that do not match the declared image type are all
  rejected and write **no** row; so is a cross-user save.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import LogEventStatus
from app.models.attachments import LogAttachment
from app.models.identity import User
from app.models.log_events import LogEvent
from app.schemas.attachments import MAX_ATTACHMENT_BYTES
from app.services.attachments import (
    AttachmentForbidden,
    AttachmentInvalidContentType,
    AttachmentTooLarge,
    ingest_upload,
)

#: Minimal byte payloads whose leading signature is a real image of each type.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 8
_WEBP_BYTES = b"RIFF\x10\x00\x00\x00WEBPVP8 " + b"\x00" * 8


@pytest.fixture
def session(db_engine: Engine) -> Iterator[Session]:
    factory = create_session_factory(db_engine)
    with factory() as db_session:
        yield db_session


@pytest.fixture
def user(session: Session) -> User:
    row = User()
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


@pytest.fixture
def log_event(session: Session, user: User) -> LogEvent:
    row = LogEvent(user_id=user.id, raw_text="label photo", status=LogEventStatus.PENDING)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _count(session: Session) -> int:
    return session.query(LogAttachment).count()


def test_default_flow_persists_no_attachment(
    session: Session, user: User, log_event: LogEvent
) -> None:
    result = ingest_upload(
        session,
        owner_id=user.id,
        current_user=user,
        log_event_id=log_event.id,
        data=_PNG_BYTES,
        content_type="image/png",
        # save defaults to False — discard by default.
    )
    assert result is None
    assert _count(session) == 0


def test_explicit_save_persists_exactly_one_attachment(
    session: Session, user: User, log_event: LogEvent
) -> None:
    result = ingest_upload(
        session,
        owner_id=user.id,
        current_user=user,
        log_event_id=log_event.id,
        data=_JPEG_BYTES,
        content_type="image/jpeg",
        save=True,
    )
    assert result is not None
    assert _count(session) == 1
    assert result.user_id == user.id
    assert result.log_event_id == log_event.id
    assert result.content_type == "image/jpeg"
    assert result.byte_size == len(_JPEG_BYTES)
    assert result.content_hash == hashlib.sha256(_JPEG_BYTES).hexdigest()
    assert result.data == _JPEG_BYTES


def test_webp_upload_is_accepted(session: Session, user: User, log_event: LogEvent) -> None:
    result = ingest_upload(
        session,
        owner_id=user.id,
        current_user=user,
        log_event_id=log_event.id,
        data=_WEBP_BYTES,
        content_type="image/webp",
        save=True,
    )
    assert result is not None
    assert result.content_type == "image/webp"
    assert _count(session) == 1


def test_oversize_upload_rejected_before_storage(
    session: Session, user: User, log_event: LogEvent
) -> None:
    oversized = _PNG_BYTES + b"\x00" * (MAX_ATTACHMENT_BYTES + 1)
    with pytest.raises(AttachmentTooLarge):
        ingest_upload(
            session,
            owner_id=user.id,
            current_user=user,
            log_event_id=log_event.id,
            data=oversized,
            content_type="image/png",
            save=True,
        )
    assert _count(session) == 0


def test_invalid_content_type_rejected_before_storage(
    session: Session, user: User, log_event: LogEvent
) -> None:
    with pytest.raises(AttachmentInvalidContentType):
        ingest_upload(
            session,
            owner_id=user.id,
            current_user=user,
            log_event_id=log_event.id,
            data=b"#!/bin/sh\necho hi\n",
            content_type="application/x-sh",
            save=True,
        )
    assert _count(session) == 0


def test_content_type_byte_mismatch_rejected_before_storage(
    session: Session, user: User, log_event: LogEvent
) -> None:
    # Declared as PNG but the bytes are a JPEG: not the image it claims to be.
    with pytest.raises(AttachmentInvalidContentType):
        ingest_upload(
            session,
            owner_id=user.id,
            current_user=user,
            log_event_id=log_event.id,
            data=_JPEG_BYTES,
            content_type="image/png",
            save=True,
        )
    assert _count(session) == 0


def test_empty_upload_rejected_before_storage(
    session: Session, user: User, log_event: LogEvent
) -> None:
    with pytest.raises(AttachmentInvalidContentType):
        ingest_upload(
            session,
            owner_id=user.id,
            current_user=user,
            log_event_id=log_event.id,
            data=b"",
            content_type="image/png",
            save=True,
        )
    assert _count(session) == 0


def test_cross_user_save_fails_closed(session: Session, user: User, log_event: LogEvent) -> None:
    with pytest.raises(AttachmentForbidden):
        ingest_upload(
            session,
            owner_id=uuid.uuid4(),  # not the current user's id
            current_user=user,
            log_event_id=log_event.id,
            data=_PNG_BYTES,
            content_type="image/png",
            save=True,
        )
    assert _count(session) == 0
