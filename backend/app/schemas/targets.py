"""Target-calculator boundary DTOs (FTY-022).

These are the estimator input/output contracts: the calculator consumes a
:class:`TargetCalculatorInput` (profile fields + the goal trajectory) and returns
a :class:`TargetCalculatorResult` (RMR, TDEE, the derived daily calorie target,
and the full assumptions snapshot). All energy is kcal and all mass is kilograms
— canonical storage units, never display units.

The :class:`DailyTargetDTO` is the persisted form of a computed result, carrying
user/goal ownership keys and the snapshot needed to reproduce the number.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums import GoalDirection, MetabolicFormula

#: Supported age range for the Mifflin-St Jeor equation (years). The equation was
#: validated on adults; ages outside this band are rejected at the boundary.
MIN_AGE_YEARS = 13
MAX_AGE_YEARS = 120


class TargetCalculatorInput(BaseModel):
    """Deterministic input to the target calculator.

    ``start_weight_kg`` / ``target_weight_kg`` and ``start_date`` / ``target_date``
    define the planned trajectory; ``height_m`` and ``age_years`` come from the
    profile (age derived from ``birth_year``). The horizon must be strictly
    positive.
    """

    model_config = ConfigDict(extra="forbid")

    metabolic_formula: MetabolicFormula
    height_m: float = Field(gt=0, le=3.0)
    age_years: int = Field(ge=MIN_AGE_YEARS, le=MAX_AGE_YEARS)
    start_weight_kg: float = Field(gt=0, le=1000.0)
    target_weight_kg: float = Field(gt=0, le=1000.0)
    start_date: date
    target_date: date

    @model_validator(mode="after")
    def _check_positive_horizon(self) -> TargetCalculatorInput:
        if self.target_date <= self.start_date:
            raise ValueError("target_date must be after start_date")
        return self

    @property
    def horizon_days(self) -> int:
        """Whole days from start to target date (always ``>= 1``)."""

        return (self.target_date - self.start_date).days


class TargetAssumptions(BaseModel):
    """Snapshot of every documented assumption behind a computed target.

    Persisted with each daily target so guidance can always be explained and
    reproduced, even if the constants are later tuned. Values are sourced from
    :mod:`app.estimator.constants`.
    """

    model_config = ConfigDict(extra="forbid")

    model: str
    baseline_activity_multiplier: float
    energy_density_kcal_per_kg: float
    rmr_mass_coefficient_kcal_per_kg: float
    safety_floor_kcal: int
    safety_ceiling_kcal: int
    rounding: str


class TargetCalculatorResult(BaseModel):
    """Deterministic output of the target calculator."""

    model_config = ConfigDict(extra="forbid")

    rmr_kcal: float
    tdee_kcal: float
    daily_calorie_target_kcal: int
    direction: GoalDirection
    horizon_days: int
    #: True when the raw target fell outside ``[floor, ceiling]`` and was clamped
    #: to the boundary — i.e. the requested trajectory is not safely achievable in
    #: the requested time and the returned number is the safe limit, not the plan.
    clamped: bool
    assumptions: TargetAssumptions


class DailyTargetDTO(BaseModel):
    """Persisted daily target, built from the ORM row.

    Carries the user/goal ownership keys plus the inputs and assumptions snapshot
    so the derived number is fully reproducible.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    goal_id: uuid.UUID
    for_date: date
    rmr_kcal: float
    tdee_kcal: float
    daily_calorie_target_kcal: int
    clamped: bool
    inputs: dict[str, Any]
    assumptions: dict[str, Any]
    created_at: datetime
