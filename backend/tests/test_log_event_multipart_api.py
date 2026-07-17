"""Unified text+image create route tests (FTY-375, ``log-event-images.md``).

The security gates this story must prove at the HTTP boundary:

- **JSON path unchanged**: the ``application/json`` create is served by the
  untouched handler (FastAPI-native validation, no attachment writes) and every
  non-multipart body falls through to it.
- **Fail-closed ingestion**: every invalid multipart submission — oversize,
  wrong type, bad signature, over-count, empty, malformed parts, cross-user —
  writes **no** event, **no** attachment, enqueues **nothing**, and returns a
  fixed, content-free error body.
- **Transient retention**: a valid mixed submission persists one transient row
  per image tied to the created ``pending`` event; ``save`` (query or form
  field) promotes them to ordinary saved rows.
- **Replay re-ingests nothing**: a keyed replay returns the stored event and
  ignores its image parts entirely (not validated, not persisted, no second
  job); a voided stored event fails closed ``404``.
- **Privacy**: image bytes/hashes and ``raw_text`` never reach logs, the job
  payload (ids only), or error bodies.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.db import create_session_factory
from app.models.attachments import LogAttachment
from app.models.log_events import LogEvent
from app.schemas.attachments import MAX_ATTACHMENT_BYTES
from tests.conftest import RecordingEnqueuer

#: Minimal byte payloads whose leading signature is a real image of each type.
_PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
_JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01" + b"\x00" * 8


def _register(client: TestClient, email: str) -> tuple[str, str]:
    resp = client.post("/api/auth/register", json={"email": email, "password": "a-good-password"})
    assert resp.status_code == 201
    body = resp.json()
    return body["user"]["id"], f"Bearer {body['token']['access_token']}"


def _payload_part(payload: dict[str, object]) -> tuple[str, tuple[None, bytes, str]]:
    """Build the JSON ``payload`` part as a multipart file tuple."""

    return ("payload", (None, json.dumps(payload).encode(), "application/json"))


def _image_part(
    data: bytes, content_type: str, name: str = "img.bin"
) -> tuple[str, tuple[str, bytes, str]]:
    return ("image", (name, data, content_type))


def _attachments(db_engine: Engine) -> list[LogAttachment]:
    factory = create_session_factory(db_engine)
    with factory() as session:
        return list(session.scalars(select(LogAttachment)).all())


def _event_count(db_engine: Engine) -> int:
    factory = create_session_factory(db_engine)
    with factory() as session:
        return session.query(LogEvent).count()


def _assert_nothing_written(
    db_engine: Engine, enqueuer: RecordingEnqueuer, events_before: int
) -> None:
    assert _event_count(db_engine) == events_before
    assert _attachments(db_engine) == []
    assert enqueuer.calls == []


# ---------------------------------------------------------------------------
# JSON path regression (content negotiation leaves it untouched)
# ---------------------------------------------------------------------------


def test_json_create_path_unchanged_and_writes_no_attachment(
    client: TestClient, enqueuer: RecordingEnqueuer, db_engine: Engine
) -> None:
    """The ``application/json`` create behaves exactly as before FTY-375."""

    user_id, auth = _register(client, "json-regression@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "two eggs and toast", "idempotency_key": "json-key-1"},
    )
    replay = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": "two eggs and toast", "idempotency_key": "json-key-1"},
    )

    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"
    assert replay.status_code == 200
    assert replay.json()["id"] == resp.json()["id"]
    assert len(enqueuer.calls) == 1
    # The JSON path never touches log_attachments.
    assert _attachments(db_engine) == []

    # Its validation errors keep FastAPI's native list shape (the multipart
    # path's fixed-string details never bleed into the JSON contract).
    invalid = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        json={"raw_text": ""},
    )
    assert invalid.status_code == 422
    assert isinstance(invalid.json()["detail"], list)


def test_non_multipart_body_falls_through_to_json_handler(client: TestClient) -> None:
    """Only ``multipart/form-data`` requests are claimed by the multipart route."""

    user_id, auth = _register(client, "fallthrough@example.com")

    urlencoded = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        data={"payload": "{}"},
    )

    # An urlencoded body reaches the JSON handler (as before FTY-375) and fails
    # its native body validation — not the multipart route's fixed details.
    assert urlencoded.status_code == 422
    assert isinstance(urlencoded.json()["detail"], list)


# ---------------------------------------------------------------------------
# Multipart happy paths
# ---------------------------------------------------------------------------


def test_multipart_text_and_images_creates_event_transient_rows_one_job(
    client: TestClient, enqueuer: RecordingEnqueuer, db_engine: Engine
) -> None:
    user_id, auth = _register(client, "mixed@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        files=[
            _payload_part({"raw_text": "2 of these bars"}),
            _image_part(_PNG_BYTES, "image/png", "label.png"),
            _image_part(_JPEG_BYTES, "image/jpeg", "bar.jpg"),
        ],
    )

    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    assert body["raw_text"] == "2 of these bars"

    rows = _attachments(db_engine)
    assert len(rows) == 2
    by_type = {row.content_type: row for row in rows}
    assert set(by_type) == {"image/png", "image/jpeg"}
    for data, content_type in ((_PNG_BYTES, "image/png"), (_JPEG_BYTES, "image/jpeg")):
        row = by_type[content_type]
        assert row.transient is True
        assert row.user_id == uuid.UUID(user_id)
        assert row.log_event_id == uuid.UUID(body["id"])
        assert row.byte_size == len(data)
        assert row.content_hash == hashlib.sha256(data).hexdigest()
        assert row.data == data

    # Exactly one job, ids only (the recording enqueuer's whole signature).
    assert enqueuer.calls == [(uuid.UUID(body["id"]), uuid.UUID(user_id))]


def test_multipart_text_only_is_equivalent_to_json_create(
    client: TestClient, enqueuer: RecordingEnqueuer, db_engine: Engine
) -> None:
    user_id, auth = _register(client, "text-only-multipart@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        files=[_payload_part({"raw_text": "  a banana  "})],
    )

    assert resp.status_code == 201
    assert resp.json()["status"] == "pending"
    assert resp.json()["raw_text"] == "a banana"
    assert _attachments(db_engine) == []
    assert len(enqueuer.calls) == 1


def test_image_only_submission_stores_photo_log_marker(
    client: TestClient, db_engine: Engine
) -> None:
    user_id, auth = _register(client, "image-only@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        files=[_payload_part({}), _image_part(_PNG_BYTES, "image/png")],
    )

    assert resp.status_code == 201
    assert resp.json()["raw_text"] == "Photo log"
    assert len(_attachments(db_engine)) == 1


@pytest.mark.parametrize("channel", ["query", "form"])
def test_save_writes_ordinary_saved_rows(
    client: TestClient, db_engine: Engine, channel: str
) -> None:
    """``save=true`` (query or form field) promotes the images to saved rows."""

    user_id, auth = _register(client, f"save-{channel}@example.com")
    files = [_payload_part({"raw_text": "keep this label"}), _image_part(_PNG_BYTES, "image/png")]
    params: dict[str, str] = {}
    if channel == "query":
        params["save"] = "true"
    else:
        files.append(("save", (None, b"true", "text/plain")))

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        params=params,
        files=files,
    )

    assert resp.status_code == 201
    rows = _attachments(db_engine)
    assert len(rows) == 1
    assert rows[0].transient is False


# ---------------------------------------------------------------------------
# Fail-closed rejection: no event, no attachment, no enqueue, content-free body
# ---------------------------------------------------------------------------


def test_oversize_image_rejected_413(
    client: TestClient, enqueuer: RecordingEnqueuer, db_engine: Engine
) -> None:
    user_id, auth = _register(client, "oversize-mixed@example.com")
    before = _event_count(db_engine)
    oversized = _PNG_BYTES + b"\x00" * (MAX_ATTACHMENT_BYTES + 1)

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        files=[_payload_part({"raw_text": "x"}), _image_part(oversized, "image/png")],
    )

    assert resp.status_code == 413
    assert resp.json()["detail"] == "image exceeds the maximum upload size"
    _assert_nothing_written(db_engine, enqueuer, before)


@pytest.mark.parametrize(
    ("data", "content_type"),
    [
        (b"#!/bin/sh\necho hi\n", "text/plain"),  # disallowed declared type
        (_JPEG_BYTES, "image/png"),  # signature does not match declared type
        (b"", "image/png"),  # empty bytes are not an image
    ],
)
def test_invalid_image_rejected_415(
    client: TestClient,
    enqueuer: RecordingEnqueuer,
    db_engine: Engine,
    data: bytes,
    content_type: str,
) -> None:
    user_id, auth = _register(client, f"badtype-{content_type.replace('/', '-')}@example.com")
    before = _event_count(db_engine)

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        files=[_payload_part({"raw_text": "x"}), _image_part(data, content_type)],
    )

    assert resp.status_code == 415
    assert resp.json()["detail"] == "upload is not an allowed image type"
    _assert_nothing_written(db_engine, enqueuer, before)


def test_over_count_rejected_422_before_image_validation(
    client: TestClient, enqueuer: RecordingEnqueuer, db_engine: Engine
) -> None:
    user_id, auth = _register(client, "overcount@example.com")
    before = _event_count(db_engine)

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        files=[
            _payload_part({"raw_text": "x"}),
            # Five parts — over MAX_SUBMISSION_IMAGES (4). The last is not even a
            # valid image: the count cap must reject before per-image validation.
            *[_image_part(_PNG_BYTES, "image/png") for _ in range(4)],
            _image_part(b"junk", "text/plain"),
        ],
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == "too many image parts"
    _assert_nothing_written(db_engine, enqueuer, before)


@pytest.mark.parametrize(
    ("files", "detail"),
    [
        # Empty submission: no text, no images.
        ([_payload_part({})], "submission requires text or at least one image"),
        # Unknown part name.
        (
            [_payload_part({"raw_text": "x"}), ("weird", (None, b"1", "text/plain"))],
            "unexpected multipart part",
        ),
        # Duplicate payload part.
        (
            [_payload_part({"raw_text": "x"}), _payload_part({"raw_text": "y"})],
            "payload part is missing or invalid",
        ),
        # Missing payload part.
        ([_image_part(_PNG_BYTES, "image/png")], "payload part is missing or invalid"),
        # Non-JSON payload part.
        (
            [("payload", (None, b"not json", "application/json"))],
            "payload part is missing or invalid",
        ),
        # Whitespace-only raw_text.
        ([_payload_part({"raw_text": "   "})], "payload part is missing or invalid"),
        # Unknown payload key.
        (
            [_payload_part({"raw_text": "x", "status": "completed"})],
            "payload part is missing or invalid",
        ),
        # Oversized raw_text.
        ([_payload_part({"raw_text": "x" * 2001})], "payload part is missing or invalid"),
        # Empty idempotency key.
        (
            [_payload_part({"raw_text": "x", "idempotency_key": "  "})],
            "payload part is missing or invalid",
        ),
        # Malformed save form field.
        (
            [_payload_part({"raw_text": "x"}), ("save", (None, b"banana", "text/plain"))],
            "save flag is invalid",
        ),
    ],
)
def test_malformed_submission_rejected_422(
    client: TestClient,
    enqueuer: RecordingEnqueuer,
    db_engine: Engine,
    files: list[tuple[str, tuple[str | None, bytes, str]]],
    detail: str,
) -> None:
    user_id, auth = _register(client, f"malformed-{abs(hash(detail)) % 10_000}@example.com")
    before = _event_count(db_engine)

    resp = client.post(
        f"/api/users/{user_id}/log-events", headers={"Authorization": auth}, files=files
    )

    assert resp.status_code == 422
    assert resp.json()["detail"] == detail
    _assert_nothing_written(db_engine, enqueuer, before)


def test_cross_user_multipart_fails_closed_404(
    client: TestClient, enqueuer: RecordingEnqueuer, db_engine: Engine
) -> None:
    _alice_id, alice_auth = _register(client, "alice-mixed@example.com")
    bob_id, _bob_auth = _register(client, "bob-mixed@example.com")
    before = _event_count(db_engine)

    resp = client.post(
        f"/api/users/{bob_id}/log-events",
        headers={"Authorization": alice_auth},
        files=[_payload_part({"raw_text": "not my log"}), _image_part(_PNG_BYTES, "image/png")],
    )

    assert resp.status_code == 404
    _assert_nothing_written(db_engine, enqueuer, before)


def test_unauthenticated_multipart_401(client: TestClient, db_engine: Engine) -> None:
    user_id, _auth = _register(client, "noauth-mixed@example.com")

    resp = client.post(
        f"/api/users/{user_id}/log-events",
        files=[_payload_part({"raw_text": "x"}), _image_part(_PNG_BYTES, "image/png")],
    )

    assert resp.status_code == 401
    assert _attachments(db_engine) == []


# ---------------------------------------------------------------------------
# Idempotent replay re-ingests nothing
# ---------------------------------------------------------------------------


def test_keyed_replay_ingests_no_images_and_enqueues_nothing(
    client: TestClient, enqueuer: RecordingEnqueuer, db_engine: Engine
) -> None:
    user_id, auth = _register(client, "replay-mixed@example.com")
    key = "mixed-outbox-key-1"

    first = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        files=[
            _payload_part({"raw_text": "2 of these bars", "idempotency_key": key}),
            _image_part(_PNG_BYTES, "image/png"),
        ],
    )
    # The replay carries divergent, *invalid* image parts and an over-count —
    # all ignored entirely (not validated, not persisted), like the divergent
    # raw_text.
    replay = client.post(
        f"/api/users/{user_id}/log-events",
        headers={"Authorization": auth},
        files=[
            _payload_part({"raw_text": "something else", "idempotency_key": key}),
            *[_image_part(b"not an image", "text/plain") for _ in range(5)],
        ],
    )

    assert first.status_code == 201
    assert replay.status_code == 200
    assert replay.json()["id"] == first.json()["id"]
    assert replay.json()["raw_text"] == "2 of these bars"
    assert len(_attachments(db_engine)) == 1
    assert len(enqueuer.calls) == 1


def test_keyed_replay_of_voided_event_fails_closed_404(
    client: TestClient, enqueuer: RecordingEnqueuer, db_engine: Engine
) -> None:
    user_id, auth = _register(client, "replay-voided-mixed@example.com")
    key = "mixed-outbox-key-2"
    files = [
        _payload_part({"raw_text": "mistaken entry", "idempotency_key": key}),
        _image_part(_PNG_BYTES, "image/png"),
    ]

    first = client.post(
        f"/api/users/{user_id}/log-events", headers={"Authorization": auth}, files=files
    )
    assert first.status_code == 201
    voided = client.delete(
        f"/api/users/{user_id}/log-events/{first.json()['id']}",
        headers={"Authorization": auth},
    )
    assert voided.status_code == 204

    replay = client.post(
        f"/api/users/{user_id}/log-events", headers={"Authorization": auth}, files=files
    )

    assert replay.status_code == 404
    # No replacement row, no re-ingest, no second job.
    assert _event_count(db_engine) == 1
    assert len(_attachments(db_engine)) == 1
    assert len(enqueuer.calls) == 1


# ---------------------------------------------------------------------------
# Privacy: nothing sensitive reaches logs, the job payload, or error bodies
# ---------------------------------------------------------------------------


def test_no_image_bytes_hashes_or_raw_text_reach_logs_or_errors(
    client: TestClient,
    enqueuer: RecordingEnqueuer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user_id, auth = _register(client, "privacy-mixed@example.com")
    raw_text = "private snack description"
    image_hash = hashlib.sha256(_PNG_BYTES).hexdigest()

    with caplog.at_level(logging.DEBUG):
        created = client.post(
            f"/api/users/{user_id}/log-events",
            headers={"Authorization": auth},
            files=[_payload_part({"raw_text": raw_text}), _image_part(_PNG_BYTES, "image/png")],
        )
        rejected = client.post(
            f"/api/users/{user_id}/log-events",
            headers={"Authorization": auth},
            files=[_payload_part({"raw_text": raw_text}), _image_part(b"junk", "image/png")],
        )

    assert created.status_code == 201
    assert rejected.status_code == 415

    # Logs carry neither the raw text nor any image-derived value.
    log_text = "\n".join(record.getMessage() for record in caplog.records)
    assert raw_text not in log_text
    assert image_hash not in log_text
    assert "PNG" not in log_text

    # The error body is a fixed action description only.
    assert rejected.json() == {"detail": "upload is not an allowed image type"}
    assert raw_text not in rejected.text

    # The job payload is ids-only by construction: the enqueue seam's entire
    # argument surface is the (log_event_id, user_id) pair.
    assert enqueuer.calls == [(uuid.UUID(created.json()["id"]), uuid.UUID(user_id))]
