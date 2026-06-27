"""Weight-entry boundary DTOs (FTY-070).

The create request and the entry DTO are contracts consumed by the mobile
weight-trend chart (FTY-074). ``weight`` in the request is in the caller's
``units_preference`` (kg for ``metric``, lb for ``imperial``); the service
converts it to canonical kg before storage. The DTO always returns
``weight_kg`` in canonical kilograms.

``effective_date`` is the calendar day the reading applies to (the axis the
chart plots against), not the row-creation timestamp.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field


class WeightEntryCreateRequest(BaseModel):
    """Request body for ``POST /api/users/{user_id}/weight-entries``.

    ``weight`` is in the user's ``units_preference`` (kg for metric, lb for
    imperial); the service converts it to canonical kg on write. It must be
    strictly positive; the canonical-kg upper bound is checked in the service
    after conversion.

    ``effective_date`` is the calendar day the measurement applies to
    (``YYYY-MM-DD``); Pydantic rejects malformed date strings with ``422``.
    Unknown keys are rejected via ``extra="forbid"``.
    """

    model_config = ConfigDict(extra="forbid")

    weight: float = Field(gt=0, description="Body weight in the user's units_preference.")
    effective_date: date = Field(description="Calendar day this reading applies to (YYYY-MM-DD).")


class WeightEntryDTO(BaseModel):
    """Response body for the weight-entry create/list/delete API.

    Built directly from the :class:`~app.models.weight_entries.WeightEntry` ORM
    row. ``weight_kg`` is always canonical kilograms regardless of the user's
    display preference.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    weight_kg: float
    effective_date: date
    created_at: datetime
    updated_at: datetime
