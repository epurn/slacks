"""Transient attachment retention service tests (FTY-375, ``log-attachments.md`` v3).

The retention rule this story owns, exercised at the service boundary:

- ``stage_submission_images`` writes one row per validated image in the caller's
  open transaction — ``transient=True`` by default, ordinary saved rows
  (``transient=False``) under the submission-level ``save`` promotion — and
  fails closed on a cross-user call.
- ``purge_transient_for_event`` hard-deletes the event's transient rows only:
  saved rows survive, other events' rows are untouched, and the purge is
  idempotent. With the default retention nothing survives the purge; with
  ``save=true`` everything does.
- ``create_event`` persists a mixed submission's images atomically with the
  event and re-ingests nothing on a keyed replay.

A Postgres-parity test exercises the same write/purge round-trip against the
production datastore when ``SLACKS_TEST_DATABASE_URL`` is configured.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db import create_session_factory
from app.enums import LogEventStatus
from app.models.attachments import LogAttachment
from app.models.identity import User
from app.models.log_events import LogEvent
from app.services import log_events as log_event_service
from app.services.attachments import (
    AttachmentForbidden,
    ValidatedImage,
    purge_transient_for_event,
    stage_submission_images,
)
from tests.conftest import upgrade

_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 8

_PNG_IMAGE = ValidatedImage(data=_PNG_BYTES, content_type="image/png")
_JPEG_IMAGE = ValidatedImage(data=_JPEG_BYTES, content_type="image/jpeg")


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


def _make_event(session: Session, user: User, raw_text: str = "mixed log") -> LogEvent:
    row = LogEvent(user_id=user.id, raw_text=raw_text, status=LogEventStatus.PENDING)
    session.add(row)
    session.commit()
    session.refresh(row)
    return row


def _rows_for(session: Session, event_id: uuid.UUID) -> list[LogAttachment]:
    return list(
        session.scalars(select(LogAttachment).where(LogAttachment.log_event_id == event_id)).all()
    )


def test_stage_defaults_to_transient_rows_with_metadata(session: Session, user: User) -> None:
    event = _make_event(session, user)

    staged = stage_submission_images(
        session,
        owner_id=user.id,
        current_user=user,
        log_event_id=event.id,
        images=[_PNG_IMAGE, _JPEG_IMAGE],
    )
    session.commit()

    rows = _rows_for(session, event.id)
    assert len(staged) == len(rows) == 2
    for row in rows:
        assert row.transient is True
        assert row.user_id == user.id
        assert row.byte_size == len(row.data)
        assert len(row.content_hash) == 64
    assert {row.content_type for row in rows} == {"image/png", "image/jpeg"}


def test_stage_with_save_writes_ordinary_saved_rows(session: Session, user: User) -> None:
    event = _make_event(session, user)

    stage_submission_images(
        session,
        owner_id=user.id,
        current_user=user,
        log_event_id=event.id,
        images=[_PNG_IMAGE],
        save=True,
    )
    session.commit()

    rows = _rows_for(session, event.id)
    assert len(rows) == 1
    assert rows[0].transient is False


def test_stage_cross_user_fails_closed(session: Session, user: User) -> None:
    event = _make_event(session, user)

    with pytest.raises(AttachmentForbidden):
        stage_submission_images(
            session,
            owner_id=uuid.uuid4(),  # not the current user's id
            current_user=user,
            log_event_id=event.id,
            images=[_PNG_IMAGE],
        )
    session.rollback()
    assert _rows_for(session, event.id) == []


def test_purge_deletes_transient_rows_and_leaves_saved_rows(session: Session, user: User) -> None:
    event = _make_event(session, user)
    stage_submission_images(
        session,
        owner_id=user.id,
        current_user=user,
        log_event_id=event.id,
        images=[_PNG_IMAGE, _JPEG_IMAGE],
    )
    # An explicit-save row on the same event (the FTY-077 class) must survive.
    stage_submission_images(
        session,
        owner_id=user.id,
        current_user=user,
        log_event_id=event.id,
        images=[_PNG_IMAGE],
        save=True,
    )
    session.commit()

    purged = purge_transient_for_event(session, event.id)
    session.commit()

    assert purged == 2
    remaining = _rows_for(session, event.id)
    assert len(remaining) == 1
    assert remaining[0].transient is False

    # Idempotent: a second purge finds nothing.
    assert purge_transient_for_event(session, event.id) == 0


def test_purge_is_scoped_to_the_event(session: Session, user: User) -> None:
    event = _make_event(session, user, "first log")
    other = _make_event(session, user, "second log")
    for target in (event, other):
        stage_submission_images(
            session,
            owner_id=user.id,
            current_user=user,
            log_event_id=target.id,
            images=[_PNG_IMAGE],
        )
    session.commit()

    assert purge_transient_for_event(session, event.id) == 1
    session.commit()

    assert _rows_for(session, event.id) == []
    other_rows = _rows_for(session, other.id)
    assert len(other_rows) == 1
    assert other_rows[0].transient is True


def test_default_retention_leaves_nothing_after_purge(session: Session, user: User) -> None:
    """Discard-by-default: with ``save`` absent, no image survives estimation."""

    event = _make_event(session, user)
    stage_submission_images(
        session,
        owner_id=user.id,
        current_user=user,
        log_event_id=event.id,
        images=[_PNG_IMAGE, _JPEG_IMAGE],
    )
    session.commit()

    purge_transient_for_event(session, event.id)
    session.commit()

    assert _rows_for(session, event.id) == []


def test_save_true_rows_survive_purge(session: Session, user: User) -> None:
    event = _make_event(session, user)
    stage_submission_images(
        session,
        owner_id=user.id,
        current_user=user,
        log_event_id=event.id,
        images=[_PNG_IMAGE, _JPEG_IMAGE],
        save=True,
    )
    session.commit()

    assert purge_transient_for_event(session, event.id) == 0
    session.commit()
    assert len(_rows_for(session, event.id)) == 2


# ---------------------------------------------------------------------------
# create_event integration: same-transaction write, replay re-ingests nothing
# ---------------------------------------------------------------------------


def test_create_event_persists_images_atomically_with_event(session: Session, user: User) -> None:
    event, created = log_event_service.create_event(
        session,
        user.id,
        user,
        "2 of these bars",
        images=[_PNG_IMAGE],
    )

    assert created is True
    rows = _rows_for(session, event.id)
    assert len(rows) == 1
    assert rows[0].transient is True


def test_create_event_keyed_replay_ingests_no_images(session: Session, user: User) -> None:
    first, created = log_event_service.create_event(
        session,
        user.id,
        user,
        "2 of these bars",
        idempotency_key="svc-key-1",
        images=[_PNG_IMAGE],
    )
    replay, replay_created = log_event_service.create_event(
        session,
        user.id,
        user,
        "a divergent body",
        idempotency_key="svc-key-1",
        images=[_JPEG_IMAGE, _PNG_IMAGE],
        save_images=True,
    )

    assert created is True
    assert replay_created is False
    assert replay.id == first.id
    assert len(_rows_for(session, first.id)) == 1


# ---------------------------------------------------------------------------
# Postgres parity (FTY-143 opt-in guard)
# ---------------------------------------------------------------------------


def test_transient_write_and_purge_round_trip_on_postgres(pg_engine: Engine) -> None:
    """The transient column, its server default, and the purge work on Postgres."""

    upgrade(pg_engine, "head")
    factory = create_session_factory(pg_engine)
    with factory() as session:
        user = User()
        session.add(user)
        session.flush()
        event = LogEvent(user_id=user.id, raw_text="pg mixed log", status=LogEventStatus.PENDING)
        session.add(event)
        session.flush()
        stage_submission_images(
            session,
            owner_id=user.id,
            current_user=user,
            log_event_id=event.id,
            images=[_PNG_IMAGE],
        )
        stage_submission_images(
            session,
            owner_id=user.id,
            current_user=user,
            log_event_id=event.id,
            images=[_JPEG_IMAGE],
            save=True,
        )
        # A row inserted without the ORM default exercises the column's server
        # default — the SQLite-tolerant ``BOOLEAN DEFAULT 0`` class of DDL bug.
        session.execute(
            text(
                "INSERT INTO log_attachments "
                "(id, user_id, log_event_id, content_type, byte_size, content_hash, data, "
                "created_at, updated_at) "
                "VALUES (:id, :uid, :eid, 'image/png', 8, :hash, :data, now(), now())"
            ),
            {
                "id": str(uuid.uuid4()),
                "uid": str(user.id),
                "eid": str(event.id),
                "hash": "0" * 64,
                "data": _PNG_BYTES,
            },
        )
        session.commit()
        event_id = event.id

    with factory() as session:
        rows = _rows_for(session, event_id)
        assert len(rows) == 3
        assert sorted(row.transient for row in rows) == [False, False, True]

        purged = purge_transient_for_event(session, event_id)
        session.commit()
        assert purged == 1
        assert sorted(row.transient for row in _rows_for(session, event_id)) == [False, False]
