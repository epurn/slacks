"""Deterministic target calculator (FTY-022).

Pure functions, no I/O, no LLM, no external input: a user's profile fields plus a
weight goal in, RMR / TDEE / a daily calorie target out. Every constant is
documented in :mod:`app.estimator.constants`.

The three steps
---------------

1. **RMR** — Mifflin-St Jeor resting metabolic rate::

       RMR = 10·weight_kg + 6.25·height_cm − 5·age_years + s

   where ``s`` is the sex-dependent constant (``+5`` male, ``−161`` female)
   selected by the metabolic formula preference.

2. **TDEE** — total daily energy expenditure at the baseline (sedentary)
   activity level::

       TDEE = RMR × baseline_activity_multiplier

   Logged exercise burn is added to the day's allowance *separately* by later
   logging stories and is deliberately excluded here, to avoid double-counting
   MET-based active calories.

3. **Daily target** — a single-compartment, NIDDK-style *dynamic* energy-balance
   plan. Naively dividing the total energy deficit by the horizon ignores that
   expenditure falls as body mass falls; the NIDDK/Hall insight is that
   expenditure tracks current mass. We linearize that: expenditure at weight
   ``w`` is ``m·(a + b·w)`` where ``b`` is the Mifflin mass coefficient
   (``10 kcal/kg/day``), ``m`` the activity multiplier, and ``a`` the
   weight-independent part of RMR. With energy density ``ρ`` (kcal/kg), constant
   daily intake ``I`` drives weight by::

       ρ · dw/dt = I − m·(a + b·w)

   a first-order linear ODE whose solution is an exponential approach to the
   equilibrium weight ``w* = (I − m·a)/(m·b)``. Solving for the constant ``I``
   that moves the user from ``w0`` (start) to ``wT`` (target) in exactly ``N``
   days gives the closed form below::

       k  = m·b/ρ
       E  = exp(−k·N)
       w* = (wT − w0·E) / (1 − E)
       I  = m·(a + b·w*)

   This is a deterministic linearization of the NIDDK Body Weight Planner, not
   the full multi-compartment Hall model. It has the right limits: ``wT == w0``
   returns exactly TDEE (maintenance); a longer horizon yields a gentler target
   approaching goal-weight maintenance; an impossibly short horizon yields an
   extreme target that the safety floor/ceiling then refuses.

A safety floor (and ceiling) clamps the final number: a target below the
clinically conservative minimum for unsupervised dieting is never returned as
guidance — it is clamped up to the floor and flagged via ``clamped``.
"""

from __future__ import annotations

import math

from app.enums import GoalDirection, MetabolicFormula
from app.estimator import constants
from app.schemas.targets import (
    TargetAssumptions,
    TargetCalculatorInput,
    TargetCalculatorResult,
)

#: Human-readable identifier of the model, persisted in the assumptions snapshot.
MODEL_NAME = "mifflin_st_jeor + single-compartment NIDDK-style dynamic energy balance"

_ROUNDING_NOTE = "RMR/TDEE rounded to 0.1 kcal; daily target rounded to nearest kcal"

_MIFFLIN_CONSTANT: dict[MetabolicFormula, float] = {
    MetabolicFormula.MIFFLIN_ST_JEOR_PLUS_5: constants.MIFFLIN_PLUS5_CONSTANT_KCAL,
    MetabolicFormula.MIFFLIN_ST_JEOR_MINUS_161: constants.MIFFLIN_MINUS161_CONSTANT_KCAL,
}

_SAFETY_FLOOR: dict[MetabolicFormula, int] = {
    MetabolicFormula.MIFFLIN_ST_JEOR_PLUS_5: constants.SAFETY_FLOOR_KCAL_PLUS5,
    MetabolicFormula.MIFFLIN_ST_JEOR_MINUS_161: constants.SAFETY_FLOOR_KCAL_MINUS161,
}


def resting_metabolic_rate(
    metabolic_formula: MetabolicFormula,
    weight_kg: float,
    height_m: float,
    age_years: int,
) -> float:
    """Mifflin-St Jeor RMR in kcal/day, rounded to 0.1 kcal.

    Height is converted from canonical metres to the centimetres the equation
    expects (``× 100``); the sex-dependent constant is chosen by
    ``metabolic_formula``.
    """

    height_cm = height_m * 100.0
    rmr = (
        constants.RMR_MASS_COEFFICIENT_KCAL_PER_KG * weight_kg
        + constants.MIFFLIN_HEIGHT_COEFFICIENT_KCAL_PER_CM * height_cm
        - constants.MIFFLIN_AGE_COEFFICIENT_KCAL_PER_YEAR * age_years
        + _MIFFLIN_CONSTANT[metabolic_formula]
    )
    return round(rmr, 1)


def total_daily_energy_expenditure(rmr_kcal: float) -> float:
    """TDEE = RMR × baseline (sedentary) activity multiplier, rounded to 0.1 kcal."""

    return round(rmr_kcal * constants.BASELINE_ACTIVITY_MULTIPLIER, 1)


def _weight_independent_rmr_term(
    metabolic_formula: MetabolicFormula, height_m: float, age_years: int
) -> float:
    """The part of Mifflin-St Jeor RMR that does not depend on body mass (``a``)."""

    return (
        constants.MIFFLIN_HEIGHT_COEFFICIENT_KCAL_PER_CM * (height_m * 100.0)
        - constants.MIFFLIN_AGE_COEFFICIENT_KCAL_PER_YEAR * age_years
        + _MIFFLIN_CONSTANT[metabolic_formula]
    )


def _dynamic_daily_intake(payload: TargetCalculatorInput) -> float:
    """Constant daily intake (kcal) that follows the goal trajectory.

    Closed-form solution of the linearized NIDDK-style energy-balance ODE; see the
    module docstring. Returns the raw, unrounded, unclamped intake.
    """

    m = constants.BASELINE_ACTIVITY_MULTIPLIER
    b = constants.RMR_MASS_COEFFICIENT_KCAL_PER_KG
    rho = constants.ENERGY_DENSITY_KCAL_PER_KG
    a = _weight_independent_rmr_term(payload.metabolic_formula, payload.height_m, payload.age_years)

    w0 = payload.start_weight_kg
    wt = payload.target_weight_kg
    n = payload.horizon_days

    k = (m * b) / rho
    e = math.exp(-k * n)
    # 1 - e > 0 for any positive horizon, so this never divides by zero.
    equilibrium_weight = (wt - w0 * e) / (1.0 - e)
    return m * (a + b * equilibrium_weight)


def _direction(start_weight_kg: float, target_weight_kg: float) -> GoalDirection:
    if target_weight_kg < start_weight_kg:
        return GoalDirection.LOSS
    if target_weight_kg > start_weight_kg:
        return GoalDirection.GAIN
    return GoalDirection.MAINTAIN


def _assumptions(metabolic_formula: MetabolicFormula) -> TargetAssumptions:
    return TargetAssumptions(
        model=MODEL_NAME,
        baseline_activity_multiplier=constants.BASELINE_ACTIVITY_MULTIPLIER,
        energy_density_kcal_per_kg=constants.ENERGY_DENSITY_KCAL_PER_KG,
        rmr_mass_coefficient_kcal_per_kg=constants.RMR_MASS_COEFFICIENT_KCAL_PER_KG,
        safety_floor_kcal=_SAFETY_FLOOR[metabolic_formula],
        safety_ceiling_kcal=constants.SAFETY_CEILING_KCAL,
        rounding=_ROUNDING_NOTE,
    )


def compute_targets(payload: TargetCalculatorInput) -> TargetCalculatorResult:
    """Compute RMR, TDEE, and the safety-clamped daily calorie target for a goal.

    Deterministic and total: every input that reaches here has already passed
    boundary validation (positive horizon, in-range metrics), so this never
    raises for valid input.
    """

    rmr = resting_metabolic_rate(
        payload.metabolic_formula,
        payload.start_weight_kg,
        payload.height_m,
        payload.age_years,
    )
    tdee = total_daily_energy_expenditure(rmr)

    raw_target = _dynamic_daily_intake(payload)
    rounded_target = round(raw_target)

    floor = _SAFETY_FLOOR[payload.metabolic_formula]
    ceiling = constants.SAFETY_CEILING_KCAL
    clamped_target = max(floor, min(ceiling, rounded_target))

    return TargetCalculatorResult(
        rmr_kcal=rmr,
        tdee_kcal=tdee,
        daily_calorie_target_kcal=clamped_target,
        direction=_direction(payload.start_weight_kg, payload.target_weight_kg),
        horizon_days=payload.horizon_days,
        clamped=clamped_target != rounded_target,
        assumptions=_assumptions(payload.metabolic_formula),
    )
