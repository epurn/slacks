"""Read-model construction for a ``daily_targets`` row.

Projects a persisted row to the derived-vs-overridden read-model that the
owner-scoped target endpoint and ``daily-summary.md``'s ``target`` component
surface. Per target the consumer sees the effective value (override ?? derived),
the derived value (what a reset restores), and the ``derived | user`` source flag.
"""

from __future__ import annotations

from app.models.targets import DailyTarget
from app.schemas.targets import TargetComponent, TargetReadModel


def build_target_read_model(target: DailyTarget) -> TargetReadModel:
    """Project a ``daily_targets`` row to the derived-vs-overridden read-model.

    Per target the consumer sees the effective value (override ?? derived), the
    derived value (what a reset restores), and the ``derived | user`` source flag.
    """

    return TargetReadModel(
        calories=TargetComponent(
            effective=target.effective_calorie_target_kcal,
            derived=target.daily_calorie_target_kcal,
            source=target.calorie_source,
        ),
        protein_g=TargetComponent(
            effective=target.effective_protein_target_g,
            derived=target.protein_target_g,
            source=target.protein_source,
        ),
        carbs_g=TargetComponent(
            effective=target.effective_carbs_target_g,
            derived=target.carbs_target_g,
            source=target.carbs_source,
        ),
        fat_g=TargetComponent(
            effective=target.effective_fat_target_g,
            derived=target.fat_target_g,
            source=target.fat_source,
        ),
    )
