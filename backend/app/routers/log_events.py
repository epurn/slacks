"""Log-event routes: create, list-today, and get-by-id (FTY-030).

The ``{user_id}`` path is explicit so object-level ownership is checked on every
access. A caller may only create, list, and read their own events; the service
fails closed on a mismatch and this router renders that as ``404`` so other
users' events are not even confirmed to exist. Raw text is never logged.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import CurrentUser
from app.schemas.log_events import LogEventCreateRequest, LogEventDTO
from app.services import log_events as log_event_service
from app.services.log_events import LogEventForbidden, LogEventNotFound

router = APIRouter(prefix="/api/users", tags=["log-events"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="log event not found")


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
) -> LogEventDTO:
    """Create a ``pending`` log event from raw text for the caller's own account."""

    try:
        event = log_event_service.create_event(session, user_id, current_user, payload.raw_text)
    except LogEventForbidden as exc:
        raise _NOT_FOUND from exc
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
