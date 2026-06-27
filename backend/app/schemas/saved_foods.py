"""Saved-food + alias boundary DTOs (FTY-052).

Three contracts consumed by the mobile save flow and typeahead picker (FTY-053):

- :class:`NutritionSnapshot` — the corrected nutrition crossing the save boundary
  and returned on every saved food: per-serving calories/macros plus the default
  serving size + unit, all bounds-checked here.
- :class:`SaveFoodRequest` — the explicit, deliberate save: the canonical name, the
  originating typed phrase (the alias), and the nutrition snapshot.
- :class:`SavedFoodDTO` / :class:`SavedFoodSearchResponse` — the typed saved food
  out (carrying its stored nutrition so the client re-applies it directly) and the
  bounded typeahead response.

Every free-text field is non-empty and length-bounded, and every nutrition number
is finite and within a generous sanity bound, so malformed input is rejected at the
request boundary with the standard pydantic error shape.
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import SavedFoodSource

#: Length cap for the canonical name and the typed alias/phrase, matching the
#: derived-item ``name`` column width.
MAX_NAME_LENGTH = 200
#: Length cap for the typeahead query string.
MAX_QUERY_LENGTH = 200
#: Length cap for a serving unit label (e.g. ``serving``, ``g``, ``cup``).
MAX_UNIT_LENGTH = 32

#: Generous canonical sanity bounds. Non-negativity/positivity is enforced per
#: field; these reject obviously-invalid magnitudes with a clear error rather than
#: storing nonsense. A real serving never approaches them.
MAX_ENERGY = 100_000.0
MAX_MACRO_G = 100_000.0
MAX_SERVING_SIZE = 100_000.0

#: Default and maximum number of saved foods a single typeahead search returns,
#: keeping the response bounded for the client.
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 50


def _finite(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("value must be a finite number")
    return value


class NutritionSnapshot(BaseModel):
    """Corrected per-serving nutrition for a saved food.

    ``calories`` and the serving descriptor are required; macros are optional
    because a corrected item may not have every macro resolved. All numbers are
    finite, non-negative (``serving_size`` strictly positive), and within the
    canonical sanity bounds.
    """

    model_config = ConfigDict(extra="forbid")

    calories: float = Field(ge=0, le=MAX_ENERGY)
    protein_g: float | None = Field(default=None, ge=0, le=MAX_MACRO_G)
    carbs_g: float | None = Field(default=None, ge=0, le=MAX_MACRO_G)
    fat_g: float | None = Field(default=None, ge=0, le=MAX_MACRO_G)
    serving_size: float = Field(gt=0, le=MAX_SERVING_SIZE)
    serving_unit: str = Field(min_length=1, max_length=MAX_UNIT_LENGTH)

    @field_validator("calories", "protein_g", "carbs_g", "fat_g", "serving_size")
    @classmethod
    def _is_finite(cls, value: float | None) -> float | None:
        return None if value is None else _finite(value)

    @field_validator("serving_unit")
    @classmethod
    def _unit_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("serving_unit must not be empty or whitespace only")
        return stripped


class SaveFoodRequest(BaseModel):
    """Request body for ``POST .../saved-foods``: a deliberate, user-initiated save.

    ``name`` is the canonical name to save under; ``phrase`` is the original text the
    user typed, persisted as the saved food's first alias; ``nutrition`` is the
    corrected snapshot. The server sets the saved food's ``source`` — it is not
    client-controlled in v1.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    phrase: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    nutrition: NutritionSnapshot

    @field_validator("name", "phrase")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be empty or whitespace only")
        return stripped


class SavedFoodDTO(BaseModel):
    """A user-owned saved food with its stored nutrition, returned on save and search."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    calories: float
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    serving_size: float
    serving_unit: str
    source: SavedFoodSource
    created_at: datetime
    updated_at: datetime


class SavedFoodSearchResponse(BaseModel):
    """The bounded typeahead response: the matching saved foods and the applied limit."""

    model_config = ConfigDict(from_attributes=True)

    items: list[SavedFoodDTO]
    limit: int
