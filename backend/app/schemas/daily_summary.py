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

from app.schemas.targets import TargetReadModel


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


class DailySummaryExerciseDTO(BaseModel):
    """Summed exercise burn for the day from finalized exercise items.

    Reported separately from intake; the client derives net (intake − burn).
    Rounded to 0.1 kcal. Zeroed when no finalized exercise items exist.
    """

    model_config = ConfigDict(extra="forbid")

    active_calories: float


class DailySummaryDTO(BaseModel):
    """Daily summary response DTO (FTY-071; target read-model FTY-094/FTY-095).

    Exposes separated intake, target, and exercise components for the requested
    day in the user's profile timezone. ``target`` is the calorie + macro
    read-model — each target carrying its effective value, derived value, and
    ``derived | user`` provenance (FTY-095) — or ``None`` when no active goal or no
    stored target exists for the day.
    """

    model_config = ConfigDict(extra="forbid")

    date: date
    intake: DailySummaryIntakeDTO
    #: True iff the day has at least one finalized food item. ``intake`` is zeroed
    #: both for a day the user logged nothing and for a day whose only logged food
    #: is genuinely zero-kcal, so the zero alone cannot tell the two apart. This
    #: flag is that signal: a range consumer (FTY-101 Trends adherence) excludes
    #: ``has_intake=False`` days from its logged-intake average and on/off-target
    #: denominator instead of counting every unlogged day as a real 0-kcal day.
    has_intake: bool
    target: TargetReadModel | None
    exercise: DailySummaryExerciseDTO
