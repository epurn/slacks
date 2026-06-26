"""Estimator domain: deterministic calculators (FTY-022).

The target calculator turns a user's profile and weight goal into RMR, TDEE, and
a daily calorie target. It is pure deterministic math — no LLM, no I/O, no
untrusted input — with every assumption documented in :mod:`.constants`.
"""

from __future__ import annotations

from app.estimator.calculator import (
    compute_targets,
    resting_metabolic_rate,
    total_daily_energy_expenditure,
)

__all__ = [
    "compute_targets",
    "resting_metabolic_rate",
    "total_daily_energy_expenditure",
]
