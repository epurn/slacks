"""Estimator domain (FTY-022, FTY-040).

Two concerns live here:

- **Deterministic calculators** (FTY-022): the target calculator turns a user's
  profile and weight goal into RMR, TDEE, and a daily calorie target — pure math,
  no LLM, no I/O, every assumption documented in :mod:`.constants`.
- **The async estimation job engine** (FTY-040): the pluggable
  :mod:`.pipeline`, the idempotent, retry-aware :mod:`.processing` worker core,
  the :mod:`.enqueue` seam, and the Celery :mod:`.tasks` wiring. The pipeline's
  parse/calc steps are stubbed here and implemented by FTY-042/043/044.
"""

from __future__ import annotations

from app.estimator.calculator import (
    compute_targets,
    resting_metabolic_rate,
    total_daily_energy_expenditure,
)
from app.estimator.exercise import (
    ExerciseBurn,
    net_active_calories,
    resolve_exercise,
)
from app.estimator.exercise_step import ExerciseCalculateStep
from app.estimator.met_table import (
    MET_TABLE_SOURCE,
    MET_TABLE_VERSION,
    lookup_met,
)
from app.estimator.pipeline import (
    EstimationContext,
    EstimationStep,
    NeedsClarification,
    Pipeline,
    PipelineOutcome,
    StepError,
    default_pipeline,
)
from app.estimator.processing import (
    DEFAULT_MAX_ATTEMPTS,
    EstimationEventNotFound,
    ProcessResult,
    process_estimation,
    retry_countdown,
)

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "MET_TABLE_SOURCE",
    "MET_TABLE_VERSION",
    "EstimationContext",
    "EstimationEventNotFound",
    "EstimationStep",
    "ExerciseBurn",
    "ExerciseCalculateStep",
    "NeedsClarification",
    "Pipeline",
    "PipelineOutcome",
    "ProcessResult",
    "StepError",
    "compute_targets",
    "default_pipeline",
    "lookup_met",
    "net_active_calories",
    "process_estimation",
    "resolve_exercise",
    "resting_metabolic_rate",
    "retry_countdown",
    "total_daily_energy_expenditure",
]
