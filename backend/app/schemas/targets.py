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

from app.enums import GoalDirection, MetabolicFormula, OverridableTarget, TargetSource

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
    #: Macro defaults (FTY-094), so every derived macro target is reproducible and
    #: explainable from the snapshot alone. Protein is anchored to bodyweight
    #: (``protein_anchor``); fat takes ``fat_pct_of_calories`` of the calorie
    #: target with a ``fat_floor_g_per_kg`` hormonal-health floor; carbohydrate is
    #: the non-negative remainder.
    protein_g_per_kg: float
    protein_anchor: str
    fat_pct_of_calories: float
    fat_floor_g_per_kg: float
    macro_rounding: str


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
    #: Macro targets in whole grams (FTY-094), derived from the *safety-clamped*
    #: ``daily_calorie_target_kcal`` so they match the calorie number the user is
    #: shown. Derivation order: protein (bodyweight anchor) → fat (calorie share
    #: with a hormonal floor) → carbohydrate (the non-negative remainder).
    protein_target_g: int
    carbs_target_g: int
    fat_target_g: int
    #: True when protein + fat already meet or exceed the calorie target so
    #: carbohydrate floored at 0 — the macro analogue of ``clamped``, keeping the
    #: rare over-constrained case honest rather than silently negative.
    macros_clamped: bool
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
    protein_target_g: int
    carbs_target_g: int
    fat_target_g: int
    macros_clamped: bool
    override_calorie_target_kcal: int | None
    override_protein_target_g: int | None
    override_carbs_target_g: int | None
    override_fat_target_g: int | None
    override_set_at: datetime | None
    inputs: dict[str, Any]
    assumptions: dict[str, Any]
    created_at: datetime


class TargetComponent(BaseModel):
    """One target value (calorie or a macro) with explicit provenance (FTY-095).

    ``effective`` is the number the app uses (the override when set, else the
    derived value); ``derived`` is always the current deterministic derivation —
    what a reset would restore; ``source`` says which of the two ``effective`` came
    from. All values are whole numbers in canonical units (kcal for calories, grams
    for macros).
    """

    model_config = ConfigDict(extra="forbid")

    effective: int
    derived: int
    source: TargetSource


class TargetReadModel(BaseModel):
    """A day's calorie + macro targets, each with derived-vs-overridden provenance.

    The shape both the daily-summary ``target`` component and the Profile target
    endpoint surface (FTY-095). Per target the consumer sees the effective value,
    the derived value, and the ``derived | user`` source flag, so the UI can render
    the "✎ set by you" badge and a ``[Reset]`` that restores the derived number.
    """

    model_config = ConfigDict(extra="forbid")

    calories: TargetComponent
    protein_g: TargetComponent
    carbs_g: TargetComponent
    fat_g: TargetComponent


class TargetOverrideRequest(BaseModel):
    """Set one or more manual target overrides (FTY-095).

    Every field is optional so the calorie target and each macro can be overridden
    independently, in any combination; at least one must be present (an empty body
    is rejected). Values are whole numbers in canonical units. Structural bounds
    are enforced here (calorie ``>= 1``, macros ``>= 0``); the documented
    safety-band check (reject out-of-band ``422``) lives in the service, which
    reads the exact band from the target's assumptions snapshot.
    """

    model_config = ConfigDict(extra="forbid")

    calorie_target_kcal: int | None = Field(default=None, ge=1)
    protein_target_g: int | None = Field(default=None, ge=0)
    carbs_target_g: int | None = Field(default=None, ge=0)
    fat_target_g: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _at_least_one(self) -> TargetOverrideRequest:
        if (
            self.calorie_target_kcal is None
            and self.protein_target_g is None
            and self.carbs_target_g is None
            and self.fat_target_g is None
        ):
            raise ValueError("at least one target override must be provided")
        return self


class TargetResetRequest(BaseModel):
    """Reset (clear) one or more manual target overrides (FTY-095).

    ``targets`` names the override columns to clear back to ``NULL`` so their
    effective value falls back to the derived value. ``None`` or an empty list
    resets **all** in-force overrides on the target. Resetting a target that is
    already derived is a no-op (idempotent).
    """

    model_config = ConfigDict(extra="forbid")

    targets: list[OverridableTarget] | None = None
