"""ORM models for the canonical identity and profile data model (FTY-020).

Importing this package registers every model on :data:`app.db.Base.metadata`,
which Alembic's migration environment uses as autogenerate/target metadata.
"""

from __future__ import annotations

from app.models.attachments import LogAttachment
from app.models.corrections import Correction
from app.models.derived import (
    ClarificationQuestion,
    DerivedExerciseItem,
    DerivedFoodItem,
)
from app.models.estimation import EstimationJob, EstimationRun
from app.models.food_sources import EvidenceSource, Product
from app.models.identity import AuthIdentity, User, UserProfile
from app.models.log_events import LogEvent
from app.models.saved_foods import FoodAlias, SavedFood
from app.models.targets import DailyTarget, Goal

__all__ = [
    "AuthIdentity",
    "ClarificationQuestion",
    "Correction",
    "DailyTarget",
    "DerivedExerciseItem",
    "DerivedFoodItem",
    "EstimationJob",
    "EstimationRun",
    "EvidenceSource",
    "FoodAlias",
    "Goal",
    "LogAttachment",
    "LogEvent",
    "Product",
    "SavedFood",
    "User",
    "UserProfile",
]
