"""Saved-foods + typeahead routes (FTY-052).

``POST /api/users/{user_id}/saved-foods`` deliberately saves a corrected food and
the phrase the user typed; ``GET /api/users/{user_id}/saved-foods`` returns that
user's saved foods matching a query by normalized prefix/contains so the mobile
client (FTY-053) can re-apply stored nutrition without re-estimating.

The ``{user_id}`` path is explicit so object-level ownership is checked on every
access. A cross-user save or search fails closed: the service raises
``SavedFoodForbidden`` and this router renders ``404`` — another user's foods are
never written under, returned, nor confirmed to exist. The typed alias and query
text are never logged.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import CurrentUser
from app.schemas.saved_foods import (
    MAX_QUERY_LENGTH,
    SavedFoodDTO,
    SavedFoodSearchResponse,
    SaveFoodRequest,
)
from app.services import saved_foods as saved_foods_service
from app.services.saved_foods import SavedFoodForbidden

router = APIRouter(prefix="/api/users", tags=["saved-foods"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="saved food not found")


@router.post(
    "/{user_id}/saved-foods",
    response_model=SavedFoodDTO,
    status_code=status.HTTP_201_CREATED,
)
def save_food(
    user_id: uuid.UUID,
    payload: SaveFoodRequest,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> SavedFoodDTO:
    """Save one corrected food for the caller, mapping their typed phrase to it.

    Creates one saved food from the corrected nutrition snapshot and one alias for
    the originating phrase. Cross-user saves fail closed as ``404``.
    """

    try:
        saved_food = saved_foods_service.save_food(
            session,
            user_id,
            current_user,
            payload.name,
            payload.phrase,
            payload.nutrition,
        )
    except SavedFoodForbidden as exc:
        raise _NOT_FOUND from exc
    return SavedFoodDTO.model_validate(saved_food)


@router.get("/{user_id}/saved-foods", response_model=SavedFoodSearchResponse)
def search_saved_foods(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    q: Annotated[
        str,
        Query(
            min_length=1,
            max_length=MAX_QUERY_LENGTH,
            description="Typeahead query; matched against saved-food names and aliases "
            "by normalized prefix/contains.",
        ),
    ],
) -> SavedFoodSearchResponse:
    """Return the caller's own saved foods matching ``q`` by normalized contains.

    Each result carries its stored nutrition so the client applies it directly. A
    cross-user search fails closed as ``404``.
    """

    try:
        items, limit = saved_foods_service.search_saved_foods(session, user_id, current_user, q)
    except SavedFoodForbidden as exc:
        raise _NOT_FOUND from exc
    return SavedFoodSearchResponse(
        items=[SavedFoodDTO.model_validate(item) for item in items],
        limit=limit,
    )
