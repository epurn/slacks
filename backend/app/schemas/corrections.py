"""Corrections + edit boundary DTOs (FTY-051, FTY-092).

Contracts consumed by the mobile edit UI (FTY-050), the Today timeline + sheet
(FTY-098/100), and later learning work (FTY-052):

- :class:`DerivedItemEditRequest` — the ``PATCH`` request shape (which field, the
  new value). The new value is the single untrusted number crossing this boundary;
  it is bounds-checked here (finite, non-negative) before the service applies any
  field-specific range rule.
- :class:`ItemSourceDTO` — the per-item **source descriptor** (FTY-092): the
  evidence source-type, a display-ready label, and the source ref, so a client
  renders the always-on source icon without joining ``evidence_sources`` itself.
- :class:`DerivedFoodItemDTO` / :class:`DerivedExerciseItemDTO` — the item read
  shape (returned by the edit ``PATCH`` and every Today read path): the current
  values, the immutable estimated/original snapshot, the derived ``source``
  descriptor, and the derived ``is_edited`` flag.
- :class:`CorrectionDTO` — the append-only audit record (typed item reference,
  field, old/new value, source, timestamp).
"""

from __future__ import annotations

import math
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import CandidateType, CorrectionSource, DerivedItemStatus, SourceType

#: Field-name length cap for an edit request; comfortably covers every editable
#: field while bounding unbounded input.
MAX_FIELD_NAME_LENGTH = 64


class DerivedItemEditRequest(BaseModel):
    """Request body for ``PATCH .../derived-items/{item_type}/{item_id}``.

    ``field`` names the value to override (validated against the editable set for
    the item type by the service, which fails closed on an unknown field).
    ``value`` is the new value in the item's canonical units (kcal, grams, or
    servings); it must be a finite, non-negative number — the service then applies
    the field-specific upper bound and the servings rescale rule.
    """

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, max_length=MAX_FIELD_NAME_LENGTH)
    value: float

    @field_validator("field")
    @classmethod
    def _strip_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("field must not be empty or whitespace only")
        return stripped

    @field_validator("value")
    @classmethod
    def _finite_non_negative(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("value must be a finite number")
        if value < 0:
            raise ValueError("value must be non-negative")
        return value


class ItemSourceDTO(BaseModel):
    """Per-item provenance descriptor for the Today timeline + sheet (FTY-092).

    Derived **read-only** from the item's ``evidence_sources`` row — there is no
    persisted provenance column. The client renders the always-on source icon and
    label from these three fields without joining ``evidence_sources`` /
    ``corrections`` itself:

    - ``source_type`` — the evidence-hierarchy classification; a ``model_prior``
      value is the signal to render the "≈ rough estimate · make it exact" treatment.
    - ``label`` — a human, display-ready string mapped deterministically from
      ``source_type`` / ``ref`` (e.g. "USDA", "Open Food Facts", "Label scan", the
      official-source host, "Rough estimate").
    - ``ref`` — the stable ``source_ref`` (e.g. ``usda_fdc:<id>``,
      ``open_food_facts:<barcode>``, ``official_source:<url>``) for the sheet's
      deeper provenance line. For an ``official_source`` item this is the URL only.
    """

    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    label: str
    ref: str


class DerivedFoodItemDTO(BaseModel):
    """Read shape for a food item: current values, original snapshot, provenance.

    Returned by the edit ``PATCH`` and every Today read path. ``source`` and
    ``is_edited`` are server-derived (FTY-092): ``source`` from the item's
    ``evidence_sources`` row (``None`` when no provenance record exists), and
    ``is_edited`` ``True`` iff the item carries a ``user_edit`` value-override
    correction — an amount-adjusted-only item stays ``False``.
    """

    model_config = ConfigDict(from_attributes=True)

    item_type: Literal[CandidateType.FOOD] = CandidateType.FOOD
    id: uuid.UUID
    user_id: uuid.UUID
    log_event_id: uuid.UUID
    name: str
    quantity_text: str
    unit: str | None
    amount: float | None
    status: DerivedItemStatus
    grams: float | None
    calories: float | None
    protein_g: float | None
    carbs_g: float | None
    fat_g: float | None
    calories_estimated: float | None
    protein_g_estimated: float | None
    carbs_g_estimated: float | None
    fat_g_estimated: float | None
    source: ItemSourceDTO | None = None
    is_edited: bool = False
    created_at: datetime
    updated_at: datetime


class DerivedExerciseItemDTO(BaseModel):
    """Read shape for an exercise item: current burn, original snapshot, provenance.

    Mirrors :class:`DerivedFoodItemDTO`. Exercise burn is computed from MET tables
    (recorded on the estimation run), not an ``evidence_sources`` row, so ``source``
    is ``None``; ``is_edited`` follows the same ``user_edit`` rule (a corrected
    ``active_calories`` marks it edited).
    """

    model_config = ConfigDict(from_attributes=True)

    item_type: Literal[CandidateType.EXERCISE] = CandidateType.EXERCISE
    id: uuid.UUID
    user_id: uuid.UUID
    log_event_id: uuid.UUID
    name: str
    quantity_text: str
    unit: str | None
    amount: float | None
    status: DerivedItemStatus
    active_calories: float | None
    active_calories_estimated: float | None
    source: ItemSourceDTO | None = None
    is_edited: bool = False
    created_at: datetime
    updated_at: datetime


class CorrectionDTO(BaseModel):
    """An append-only corrections audit record.

    The named contract consumed by FTY-052 and later learning work: a user-owned,
    typed reference to the corrected derived item, the changed field, the old/new
    value in canonical units, the source, and the creation timestamp.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    item_type: CandidateType
    derived_food_item_id: uuid.UUID | None
    derived_exercise_item_id: uuid.UUID | None
    field: str
    old_value: float | None
    new_value: float
    source: CorrectionSource
    created_at: datetime
