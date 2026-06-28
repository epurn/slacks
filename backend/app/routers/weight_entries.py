"""Weight-entry routes: create, list-by-range, and delete (FTY-070).

The ``{user_id}`` path is explicit so object-level ownership is checked on every
access. A caller may only create, list, and delete their own entries; the service
fails closed on a mismatch and this router renders that as ``404`` so other
users' entries are not even confirmed to exist. Weight values are never logged.

``from`` and ``to`` are query-parameter aliases because ``from`` is a Python
keyword; both are optional and default to no date restriction.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import CurrentUser
from app.schemas.weight_entries import WeightEntryCreateRequest, WeightEntryDTO
from app.services import weight_entries as weight_entry_service
from app.services.weight_entries import (
    InvalidWeightDate,
    InvalidWeightValue,
    WeightEntryForbidden,
    WeightEntryNotFound,
)

router = APIRouter(prefix="/api/users", tags=["weight-entries"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="weight entry not found")
_INVALID_RANGE = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="'from' must be on or before 'to'",
)
_INVALID_WEIGHT = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="weight is outside the plausible (0, 1000] kg range after unit conversion",
)
_INVALID_DATE = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail=(
        "effective_date must be on or after 1900-01-01 and on or before"
        " today in the user's timezone (plus one day slack)"
    ),
)


@router.post(
    "/{user_id}/weight-entries",
    response_model=WeightEntryDTO,
    status_code=status.HTTP_201_CREATED,
)
def create_weight_entry(
    user_id: uuid.UUID,
    payload: WeightEntryCreateRequest,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> WeightEntryDTO:
    """Create a weight entry at the given effective date.

    ``weight`` is in the caller's ``units_preference`` (kg for metric, lb for
    imperial); the service converts it to canonical kg on write. Returns the
    typed entry DTO with ``weight_kg`` in canonical kg.
    """

    try:
        entry = weight_entry_service.create_entry(
            session, user_id, current_user, payload.weight, payload.effective_date
        )
    except WeightEntryForbidden as exc:
        raise _NOT_FOUND from exc
    except InvalidWeightDate as exc:
        raise _INVALID_DATE from exc
    except InvalidWeightValue as exc:
        raise _INVALID_WEIGHT from exc
    return WeightEntryDTO.model_validate(entry)


@router.get("/{user_id}/weight-entries", response_model=list[WeightEntryDTO])
def list_weight_entries(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    from_date: Annotated[
        date | None,
        Query(alias="from", description="Inclusive start of the effective-date range."),
    ] = None,
    to_date: Annotated[
        date | None,
        Query(alias="to", description="Inclusive end of the effective-date range."),
    ] = None,
) -> list[WeightEntryDTO]:
    """List the caller's own entries whose effective date falls in ``[from, to]``.

    Both bounds are optional (no bound means open-ended). When both are given,
    ``from`` must be on or before ``to`` (422 otherwise). Ordered oldest-first.
    """

    if from_date is not None and to_date is not None and from_date > to_date:
        raise _INVALID_RANGE
    try:
        entries = weight_entry_service.list_entries(
            session, user_id, current_user, from_date, to_date
        )
    except WeightEntryForbidden as exc:
        raise _NOT_FOUND from exc
    return [WeightEntryDTO.model_validate(e) for e in entries]


@router.delete(
    "/{user_id}/weight-entries/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_weight_entry(
    user_id: uuid.UUID,
    entry_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> Response:
    """Delete one of the caller's own weight entries.

    The query is scoped to the caller so a cross-user ``entry_id`` is
    indistinguishable from a missing one; both return ``404``.
    """

    try:
        weight_entry_service.delete_entry(session, user_id, current_user, entry_id)
    except WeightEntryForbidden as exc:
        raise _NOT_FOUND from exc
    except WeightEntryNotFound as exc:
        raise _NOT_FOUND from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
