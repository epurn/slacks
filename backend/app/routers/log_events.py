"""Log-event routes: create, list-today, and get-by-id (FTY-030, FTY-040).

The ``{user_id}`` path is explicit so object-level ownership is checked on every
access. A caller may only create, list, and read their own events; the service
fails closed on a mismatch and this router renders that as ``404`` so other
users' events are not even confirmed to exist. Raw text is never logged.

FTY-040 extends the create path: once a ``pending`` event is committed, an
estimation job is enqueued (through the swappable enqueuer seam) so the worker
picks it up asynchronously.

FTY-064 adds the nutrition-label upload path: a captured label image is posted as
the raw request body and resolved synchronously in-request (the raw image is
discarded by default and never enqueued, so it cannot reach the broker). See
``docs/contracts/label-upload.md``.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import CurrentUser
from app.estimator.enqueue import EstimationEnqueuer, get_enqueuer
from app.estimator.label_step import LabelInput
from app.estimator.label_upload import LabelProcessor, get_label_processor
from app.schemas.log_events import LogEventCreateRequest, LogEventDTO
from app.services import log_events as log_event_service
from app.services.attachments import (
    AttachmentInvalidContentType,
    AttachmentTooLarge,
    validate_upload,
)
from app.services.log_events import LogEventForbidden, LogEventNotFound

router = APIRouter(prefix="/api/users", tags=["log-events"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="log event not found")

#: The non-sensitive raw-text marker stored on a label-capture event. A label
#: upload carries no natural-language text, so this fixed, content-free string
#: stands in for the timeline; the food facts come from the extracted panel.
LABEL_EVENT_RAW_TEXT = "Nutrition label photo"


async def _read_image_body(request: Request) -> bytes:
    """Read the raw uploaded image bytes off the request body.

    Reading the body is async; the path operation that consumes these bytes is a
    sync function (so its blocking extraction runs in the threadpool), so the read
    is isolated in this dependency.
    """

    return await request.body()


@router.post(
    "/{user_id}/log-events",
    response_model=LogEventDTO,
    status_code=status.HTTP_201_CREATED,
)
def create_log_event(
    user_id: uuid.UUID,
    payload: LogEventCreateRequest,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    enqueue: Annotated[EstimationEnqueuer, Depends(get_enqueuer)],
) -> LogEventDTO:
    """Create a ``pending`` log event and enqueue its estimation job.

    The event is committed first; only then is the job published, so the worker
    never races ahead of a persisted event. The payload carries ids only — never
    the raw text.
    """

    try:
        event = log_event_service.create_event(session, user_id, current_user, payload.raw_text)
    except LogEventForbidden as exc:
        raise _NOT_FOUND from exc
    enqueue(log_event_id=event.id, user_id=event.user_id)
    return LogEventDTO.model_validate(event)


@router.post(
    "/{user_id}/log-events/label",
    response_model=LogEventDTO,
    status_code=status.HTTP_201_CREATED,
)
def upload_label_event(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    data: Annotated[bytes, Depends(_read_image_body)],
    process_label: Annotated[LabelProcessor, Depends(get_label_processor)],
    content_type: Annotated[str | None, Header()] = None,
    save: Annotated[
        bool,
        Query(description="Retain the raw image as a log_attachment (FTY-077). Defaults to off."),
    ] = False,
) -> LogEventDTO:
    """Create a label event from an uploaded image and extract it in-request (FTY-064).

    The image is the raw request body; its declared type is the ``Content-Type``
    header. It is validated as **data** (size, content-type allowlist, magic-number
    signature) at the trust boundary before any work — an invalid upload fails
    closed with ``413``/``415`` and no event is created. A valid upload creates a
    ``pending`` event, then the FTY-061 label pipeline resolves it synchronously:
    the raw image only ever lives in this request (it is never enqueued), and is
    retained as a ``log_attachment`` only when ``save`` is set, discarded by
    default. Returns the event at its post-extraction status. Errors carry only an
    HTTP status — never image bytes or extracted content.
    """

    try:
        canonical_type = validate_upload(data, content_type or "")
    except AttachmentTooLarge as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="image exceeds the maximum upload size",
        ) from exc
    except AttachmentInvalidContentType as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="upload is not an allowed image type",
        ) from exc

    try:
        event = log_event_service.create_event(session, user_id, current_user, LABEL_EVENT_RAW_TEXT)
    except LogEventForbidden as exc:
        raise _NOT_FOUND from exc

    label = LabelInput(data=data, content_type=canonical_type, save=save)
    process_label(session, log_event_id=event.id, user_id=event.user_id, label_upload=label)
    session.refresh(event)
    return LogEventDTO.model_validate(event)


@router.get("/{user_id}/log-events", response_model=list[LogEventDTO])
def list_log_events(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    day: Annotated[
        date | None,
        Query(description="Calendar day (YYYY-MM-DD) in the user's timezone; defaults to today."),
    ] = None,
) -> list[LogEventDTO]:
    """List the caller's own events for ``day`` (their local timezone)."""

    try:
        events = log_event_service.list_events_for_day(session, user_id, current_user, day)
    except LogEventForbidden as exc:
        raise _NOT_FOUND from exc
    return [LogEventDTO.model_validate(event) for event in events]


@router.get("/{user_id}/log-events/{event_id}", response_model=LogEventDTO)
def get_log_event(
    user_id: uuid.UUID,
    event_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> LogEventDTO:
    """Return one of the caller's own events by id, or ``404`` otherwise."""

    try:
        event = log_event_service.get_event(session, user_id, current_user, event_id)
    except (LogEventForbidden, LogEventNotFound) as exc:
        raise _NOT_FOUND from exc
    return LogEventDTO.model_validate(event)
