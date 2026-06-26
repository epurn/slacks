"""Weight-goal boundary DTOs (FTY-022).

A goal is a user-owned plan: "from ``start_weight_kg`` on ``start_date`` reach
``target_weight_kg`` by ``target_date``." The start snapshot is captured when the
goal is created so the planned trajectory (and therefore the derived daily
target) is deterministic and does not drift as the user's measured weight
changes. Body weight is stored in canonical kilograms; display units are a
separate user preference and never change what is stored.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GoalCreateRequest(BaseModel):
    """Request to create a weight goal.

    ``start_weight_kg`` and ``start_date`` are the trajectory origin. Callers may
    omit them to default to the user's current weight / today at the service
    boundary; when supplied they pin the plan explicitly. The calculator requires
    a strictly positive horizon, enforced here so an impossible plan is rejected
    at the boundary rather than producing a nonsensical target.
    """

    model_config = ConfigDict(extra="forbid")

    target_weight_kg: float = Field(gt=0, le=1000.0)
    target_date: date
    start_weight_kg: float = Field(gt=0, le=1000.0)
    start_date: date

    @model_validator(mode="after")
    def _check_positive_horizon(self) -> GoalCreateRequest:
        if self.target_date <= self.start_date:
            raise ValueError("target_date must be after start_date")
        return self


class GoalDTO(BaseModel):
    """Response/representation of a persisted goal, built from the ORM row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    start_weight_kg: float
    start_date: date
    target_weight_kg: float
    target_date: date
    is_active: bool
    created_at: datetime
    updated_at: datetime
