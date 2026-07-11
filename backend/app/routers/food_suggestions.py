"""Contextual food-suggestion route (FTY-340).

``GET /api/food-suggestions`` returns a bounded quick-add list for the signed-in
user, ranked from their own saved foods and completed log history. The endpoint is
read-only, owner-scoped by the bearer token, and performs no network or LLM work.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import CurrentUser, get_current_time
from app.schemas.food_suggestions import (
    DEFAULT_FOOD_SUGGESTION_LIMIT,
    MAX_FOOD_SUGGESTION_LIMIT,
    FoodSuggestionResponse,
)
from app.services import food_suggestions as food_suggestions_service

router = APIRouter(prefix="/api", tags=["food-suggestions"])


@router.get("/food-suggestions", response_model=FoodSuggestionResponse)
def get_food_suggestions(
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    now: Annotated[datetime, Depends(get_current_time)],
    limit: Annotated[
        int,
        Query(
            ge=1,
            le=MAX_FOOD_SUGGESTION_LIMIT,
            description=(
                "Maximum suggestions to return. Defaults to "
                f"{DEFAULT_FOOD_SUGGESTION_LIMIT}; values above "
                f"{MAX_FOOD_SUGGESTION_LIMIT} return 422."
            ),
        ),
    ] = DEFAULT_FOOD_SUGGESTION_LIMIT,
) -> FoodSuggestionResponse:
    """Return ranked quick-add suggestions for the authenticated user."""

    items = food_suggestions_service.get_food_suggestions(
        session,
        current_user,
        now=now,
        limit=limit,
    )
    return FoodSuggestionResponse(items=items, limit=limit)
