"""Daily-summary boundary DTOs (FTY-071).

The daily-summary endpoint returns separated calorie/macro components for a day:
intake from finalized food items, calorie target from the FTY-022 calculator, and
exercise burn from finalized exercise items. Components are exposed separately so
the client can compute net (intake − burn) without server-side pre-netting.

Units are canonical throughout: energy in kcal, macros in grams. Sums are rounded
to 0.1 (one decimal place), matching the FTY-043/FTY-044 serving-math precision.

``target`` is ``None`` when no active goal or no stored daily target exists for the
requested day — an explicit null rather than a misleading zero.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict


class DailySummaryIntakeDTO(BaseModel):
    """Summed intake for the day from finalized food items.

    All values are in canonical units (kcal, grams) rounded to 0.1. Zeroed when
    no finalized food items exist for the day. Never pre-netted against burn.
    """

    model_config = ConfigDict(extra="forbid")

    calories: float
    protein_g: float
    carbs_g: float
    fat_g: float


class DailySummaryTargetDTO(BaseModel):
    """Daily calorie target for the day from the FTY-022 target calculator.

    Present only when the user has an active goal with a stored ``daily_targets``
    row for the requested day. ``None`` otherwise — no active goal, or the day
    predates the goal. Macro targets are not part of the FTY-022 contract.
    """

    model_config = ConfigDict(extra="forbid")

    #: ``daily_calorie_target_kcal`` from the stored ``daily_targets`` row.
    calories: int


class DailySummaryExerciseDTO(BaseModel):
    """Summed exercise burn for the day from finalized exercise items.

    Reported separately from intake; the client derives net (intake − burn).
    Rounded to 0.1 kcal. Zeroed when no finalized exercise items exist.
    """

    model_config = ConfigDict(extra="forbid")

    active_calories: float


class DailySummaryDTO(BaseModel):
    """Daily summary response DTO (FTY-071).

    Exposes separated intake, target, and exercise components for the requested
    day in the user's profile timezone. ``target`` is ``None`` when no active
    goal or no stored target exists for the day.
    """

    model_config = ConfigDict(extra="forbid")

    date: date
    intake: DailySummaryIntakeDTO
    target: DailySummaryTargetDTO | None
    exercise: DailySummaryExerciseDTO
