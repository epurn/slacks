"""Food-suggestion boundary DTOs (FTY-340).

The suggestions endpoint returns a bounded list of deterministic quick-add
candidates derived only from the authenticated user's saved foods and completed
food-log history. The score is included as a rounded debugging aid; clients
should treat list order as the product signal.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict

#: Default number of contextual suggestions returned when the client omits
#: ``limit``.
DEFAULT_FOOD_SUGGESTION_LIMIT = 8
#: Hard response cap. Requests above this are rejected at the HTTP boundary.
MAX_FOOD_SUGGESTION_LIMIT = 20


class FoodSuggestionDTO(BaseModel):
    """One ranked quick-add suggestion for the Today composer."""

    model_config = ConfigDict(from_attributes=True)

    label: str
    submit_phrase: str
    saved_food_id: uuid.UUID | None = None
    score: float


class FoodSuggestionResponse(BaseModel):
    """Bounded contextual food-suggestion response."""

    items: list[FoodSuggestionDTO]
    limit: int
