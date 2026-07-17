"""Multipart (text+image) log-event create route (FTY-375).

The unified text+image submission variant of ``POST /api/users/{user_id}/log-events``
(``docs/contracts/log-event-images.md``): one JSON ``payload`` part, 0..N
fail-closed validated ``image`` parts, and a submission-level ``save`` flag
(query or form field). Content negotiation happens at **route matching** —
:class:`_MultipartCreateRoute` claims only ``multipart/form-data`` requests, and
:func:`register_multipart_create_route` registers it ahead of the JSON create
route in :mod:`app.routers.log_events`, which therefore stays byte-for-byte
unchanged (same handler, same FastAPI-native validation, same error shapes).

Security posture (``docs/contracts/log-attachments.md`` v3): every image is
validated fail-closed — size, content-type allowlist, magic-number signature,
and the submission count cap — **before** any event, attachment row, or enqueue;
an invalid part rejects the whole submission. Valid images persist as transient
``log_attachments`` rows in the same transaction as the ``pending`` event
(ordinary saved rows under ``save=true``), the job payload stays ids-only, and
every rejection body is a fixed, content-free action description — image bytes,
hashes, and ``raw_text`` never reach logs, the queue, or error bodies.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.orm import Session
from starlette.datastructures import Headers, UploadFile
from starlette.formparsers import MultiPartException
from starlette.routing import Match
from starlette.types import Scope

from app.db import get_session
from app.deps import CurrentUser
from app.estimator.enqueue import EstimationEnqueuer, get_enqueuer
from app.schemas.attachments import MAX_SUBMISSION_IMAGES
from app.schemas.log_events import LogEventDTO, LogEventMultipartPayload
from app.services import log_events as log_event_service
from app.services.attachments import (
    AttachmentInvalidContentType,
    AttachmentTooLarge,
    ValidatedImage,
    validate_upload,
)
from app.services.log_events import LogEventForbidden, LogEventNotFound

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="log event not found")

#: The non-sensitive raw-text marker stored for an image-only mixed submission
#: (FTY-375): ``raw_text`` is not null and the timeline renders it, so this
#: fixed, content-free string stands in when the user attached photos without
#: typing anything (the same convention as the label path's marker).
PHOTO_LOG_EVENT_RAW_TEXT = "Photo log"

# Fixed, content-free multipart rejection bodies (FTY-375): a mixed submission
# carries sensitive log text and untrusted image bytes, so every error is a
# status plus a fixed action description — never the rejected input.
_MALFORMED_MULTIPART = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="multipart submission is malformed",
)
_INVALID_PAYLOAD_PART = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="payload part is missing or invalid",
)
_UNKNOWN_PART = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="unexpected multipart part",
)
_INVALID_SAVE_FLAG = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="save flag is invalid",
)
_EMPTY_SUBMISSION = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="submission requires text or at least one image",
)
_TOO_MANY_IMAGES = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="too many image parts",
)
_IMAGE_TOO_LARGE = HTTPException(
    status_code=status.HTTP_413_CONTENT_TOO_LARGE,
    detail="image exceeds the maximum upload size",
)
_IMAGE_INVALID_TYPE = HTTPException(
    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    detail="upload is not an allowed image type",
)

#: OpenAPI documentation for the multipart create variant, merged into the JSON
#: create operation via ``openapi_extra`` (OpenAPI keys operations by
#: path+method, so the hidden multipart route is documented on the one create
#: operation). The wire contract is ``docs/contracts/log-event-images.md``.
MULTIPART_CREATE_OPENAPI: dict[str, Any] = {
    "requestBody": {
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["payload"],
                    "properties": {
                        "payload": {
                            "type": "string",
                            "description": (
                                'JSON payload part: {"raw_text"?: str, '
                                '"idempotency_key"?: str}. Field rules match the '
                                "application/json body; raw_text may be omitted "
                                "only when at least one image part is present."
                            ),
                        },
                        "image": {
                            "type": "array",
                            "items": {"type": "string", "format": "binary"},
                            "description": (
                                "0..4 image parts (image/jpeg, image/png, image/webp; "
                                "at most 10 MiB each), validated fail-closed."
                            ),
                        },
                        "save": {
                            "type": "string",
                            "enum": ["true", "false"],
                            "description": (
                                "Optional submission-level retention choice (also "
                                "accepted as a query flag). Default false: images "
                                "are transient and purged at estimation-terminal."
                            ),
                        },
                    },
                }
            }
        }
    }
}


class _MultipartCreateRoute(APIRoute):
    """An :class:`APIRoute` that matches only ``multipart/form-data`` requests.

    Content negotiation for the create endpoint (FTY-374/FTY-375) is done at
    route matching: this route claims the multipart submissions and every other
    request falls through to the next registered route — the original JSON
    create handler, which therefore stays byte-for-byte unchanged.
    """

    def matches(self, scope: Scope) -> tuple[Match, Scope]:
        if scope["type"] == "http":
            content_type = Headers(scope=scope).get("content-type", "")
            if not content_type.strip().lower().startswith("multipart/form-data"):
                return Match.NONE, {}
        return super().matches(scope)


@dataclass(frozen=True)
class _MultipartSubmission:
    """The extracted, boundary-validated parts of a multipart create."""

    payload: LogEventMultipartPayload
    #: Each ``image`` part as ``(bytes, declared content-type)`` — untrusted and
    #: **not yet validated** (a keyed replay never validates them at all).
    images: list[tuple[bytes, str]]
    #: The ``save`` form field when present (the query flag is the alternative).
    save_field: bool | None


async def _part_bytes(value: str | UploadFile) -> bytes:
    """Return a form part's raw bytes whether it arrived as a field or a file."""

    if isinstance(value, str):
        return value.encode("utf-8")
    return await value.read()


def _parse_save_field(values: list[str]) -> bool | None:
    """Parse the optional ``save`` form field strictly (``true``/``false``)."""

    if not values:
        return None
    if len(values) > 1:
        raise _INVALID_SAVE_FLAG
    normalized = values[0].strip().lower()
    if normalized not in {"true", "false"}:
        raise _INVALID_SAVE_FLAG
    return normalized == "true"


def _parse_payload_part(parts: list[bytes]) -> LogEventMultipartPayload:
    """Validate the exactly-one JSON ``payload`` part, content-free on failure."""

    if len(parts) != 1:
        raise _INVALID_PAYLOAD_PART
    try:
        decoded = json.loads(parts[0])
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _INVALID_PAYLOAD_PART from exc
    try:
        return LogEventMultipartPayload.model_validate(decoded)
    except ValidationError as exc:
        # Never FastAPI's default validation body here: it would echo the
        # rejected input (sensitive log text) back to the caller.
        raise _INVALID_PAYLOAD_PART from exc


async def _read_multipart_submission(request: Request) -> _MultipartSubmission:
    """Extract and boundary-validate the multipart create parts (FTY-375).

    Enforces the wire shape from ``docs/contracts/log-event-images.md``: exactly
    one JSON ``payload`` part, 0..N ``image`` parts, an optional ``save`` field,
    and nothing else — a missing/duplicate/non-JSON payload, an unknown part
    name, or a malformed ``save`` value rejects the whole submission ``422``
    with a fixed, content-free body. Image bytes are only *extracted* here;
    size/type/signature validation runs in the endpoint, after the
    idempotent-replay probe (a replay ignores image parts entirely).
    """

    try:
        form = await request.form()
    except MultiPartException as exc:
        raise _MALFORMED_MULTIPART from exc

    payload_parts: list[bytes] = []
    images: list[tuple[bytes, str]] = []
    save_values: list[str] = []
    for name, value in form.multi_items():
        if name == "payload":
            payload_parts.append(await _part_bytes(value))
        elif name == "image":
            if isinstance(value, UploadFile):
                images.append((await value.read(), value.content_type or ""))
            else:
                # A bare text field declares no image content type; it fails the
                # allowlist downstream rather than being guessed at here.
                images.append((value.encode("utf-8"), ""))
        elif name == "save":
            if isinstance(value, UploadFile):
                raise _INVALID_SAVE_FLAG
            save_values.append(value)
        else:
            raise _UNKNOWN_PART

    return _MultipartSubmission(
        payload=_parse_payload_part(payload_parts),
        images=images,
        save_field=_parse_save_field(save_values),
    )


def create_log_event_multipart(
    user_id: uuid.UUID,
    submission: Annotated[_MultipartSubmission, Depends(_read_multipart_submission)],
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    enqueue: Annotated[EstimationEnqueuer, Depends(get_enqueuer)],
    response: Response,
    save: Annotated[
        bool,
        Query(
            description=(
                "Retain the submission's images as ordinary saved log_attachments "
                "rows instead of transient ones (docs/contracts/log-attachments.md). "
                "Defaults to off: discard once estimation no longer needs them."
            )
        ),
    ] = False,
) -> LogEventDTO:
    """Create a ``pending`` event from a unified text+image submission (FTY-375).

    The multipart sibling of the JSON create — same event, same idempotency,
    same single ids-only enqueue — plus fail-closed image handling
    (``docs/contracts/log-event-images.md``), in the contract's deterministic
    order: payload validation (in the dependency), then the idempotent-replay
    probe (a replay returns ``200`` and ignores image parts entirely), then the
    at-least-one-surface rule, the image count cap, and per-image
    size/type/signature validation. Any invalid image rejects the whole
    submission (``413``/``415``/``422``) with **no** event, attachment, or
    enqueue, and a fixed content-free error body.

    Valid images are persisted as ``log_attachments`` rows in the same
    transaction as the event — transient (purged at estimation-terminal) by
    default, ordinary saved rows when ``save`` is true (query or form field) —
    so the async worker can load them by event id; the job payload stays
    ids-only. Image bytes are never logged and never echoed in errors.
    """

    payload = submission.payload
    save_images = submission.save_field if submission.save_field is not None else save

    try:
        existing = log_event_service.find_keyed_replay(
            session, user_id, current_user, payload.idempotency_key
        )
    except (LogEventForbidden, LogEventNotFound) as exc:
        raise _NOT_FOUND from exc
    if existing is not None:
        # Keyed replay: first-write-wins; the image parts are not validated and
        # nothing is re-ingested or re-enqueued.
        response.status_code = status.HTTP_200_OK
        return LogEventDTO.model_validate(existing)

    if payload.raw_text is None and not submission.images:
        raise _EMPTY_SUBMISSION
    if len(submission.images) > MAX_SUBMISSION_IMAGES:
        raise _TOO_MANY_IMAGES
    try:
        validated = [
            ValidatedImage(data=data, content_type=validate_upload(data, declared))
            for data, declared in submission.images
        ]
    except AttachmentTooLarge as exc:
        raise _IMAGE_TOO_LARGE from exc
    except AttachmentInvalidContentType as exc:
        raise _IMAGE_INVALID_TYPE from exc

    raw_text = payload.raw_text if payload.raw_text is not None else PHOTO_LOG_EVENT_RAW_TEXT
    try:
        event, created = log_event_service.create_event(
            session,
            user_id,
            current_user,
            raw_text,
            idempotency_key=payload.idempotency_key,
            images=validated,
            save_images=save_images,
        )
    except (LogEventForbidden, LogEventNotFound) as exc:
        raise _NOT_FOUND from exc
    if created:
        enqueue(log_event_id=event.id, user_id=event.user_id)
    else:
        response.status_code = status.HTTP_200_OK
    return LogEventDTO.model_validate(event)


def register_multipart_create_route(router: APIRouter) -> None:
    """Register the multipart create route on ``router``.

    Must run **before** the JSON create route is registered so route matching
    tries the multipart-only route first and every non-multipart POST falls
    through to the unchanged JSON handler. Hidden from the schema: the JSON
    create operation documents both content types via
    :data:`MULTIPART_CREATE_OPENAPI`.
    """

    router.add_api_route(
        "/{user_id}/log-events",
        create_log_event_multipart,
        methods=["POST"],
        response_model=LogEventDTO,
        status_code=status.HTTP_201_CREATED,
        route_class_override=_MultipartCreateRoute,
        include_in_schema=False,
    )
