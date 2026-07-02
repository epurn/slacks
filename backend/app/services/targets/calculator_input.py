"""Calculator input / estimator adapter for the target service.

Normalises a user's profile (body constants) and a goal (the weight trajectory)
into the deterministic calculator's validated input contract
(``TargetCalculatorInput``). This is the seam between the identity/goal models and
the estimator's pure math: an incomplete profile is refused here so it can never
silently produce a bogus target.
"""

from __future__ import annotations

from datetime import date

from app.enums import MetabolicFormula
from app.models.identity import UserProfile
from app.models.targets import Goal
from app.schemas.targets import TargetCalculatorInput

from .errors import IncompleteProfileError


def derive_age_years(birth_year: int, on_date: date) -> int:
    """Whole-year age on ``on_date``.

    The profile stores only ``birth_year`` (privacy-minimal — no birth month/day),
    so age is a whole-year approximation. Documented assumption, exercised by
    tests.
    """

    return on_date.year - birth_year


def build_calculator_input(
    profile: UserProfile, goal: Goal, *, for_date: date
) -> TargetCalculatorInput:
    """Assemble a validated calculator input from a profile and goal.

    Raises :class:`IncompleteProfileError` if the profile has not captured the
    body metrics the math needs, so an incomplete profile can never silently
    produce a bogus target.
    """

    if profile.height_m is None or profile.birth_year is None:
        raise IncompleteProfileError("profile is missing height or birth year")

    formula = MetabolicFormula(profile.metabolic_formula)
    if formula is MetabolicFormula.MIFFLIN_ST_JEOR:
        # The unspecified family default carries no RMR constant: a profile that
        # has not yet captured a +5/-161 variant cannot produce a target.
        raise IncompleteProfileError("profile has not selected a metabolic formula variant")

    return TargetCalculatorInput(
        metabolic_formula=formula,
        height_m=profile.height_m,
        age_years=derive_age_years(profile.birth_year, for_date),
        start_weight_kg=goal.start_weight_kg,
        target_weight_kg=goal.target_weight_kg,
        start_date=goal.start_date,
        target_date=goal.target_date,
    )
