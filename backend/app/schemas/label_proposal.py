"""Label-parse confirmation-gate DTOs (FTY-196).

A legible nutrition-label parse lands as an **uncounted proposal** (a
``derived_food_items`` row held ``proposed``) rather than an immediately-counted
``resolved`` item, because "OCR is fallible — Fatty never silently trusts a
fallible parse" (``docs/design-philosophy.md``). Two boundary shapes back the
mobile confirm sheet (FTY-197):

- :class:`LabelProposalResponse` — the owner-scoped **read** the sheet renders: the
  proposed food values (name, serving, calories, macros) plus the ``user_label``
  source descriptor, reusing the shared item read shape so provenance is derived
  consistently. ``proposal`` is ``None`` when the event has no proposal (never
  confirmed, or the event was ``needs_clarification`` / ``failed``).
- :class:`LabelProposalConfirmRequest` — the optional **adjusted values** on
  confirm. When omitted (or empty) the parsed values commit as-is; a supplied
  value is the user's own number and commits as a correction so provenance / edited
  state stays honest per ``docs/contracts/corrections.md`` (a changed
  calorie/macro value is a ``user_edit``; an adjusted ``amount`` is a
  provenance-preserving ``amount_adjust`` rescale — the ``user_label`` provenance
  is untouched either way).
"""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.corrections import DerivedFoodItemDTO


class LabelProposalConfirmRequest(BaseModel):
    """Optional adjusted values for confirming a label proposal (FTY-196).

    Every field is optional: an empty body confirms the parsed values unchanged.
    A supplied ``calories`` / ``protein_g`` / ``carbs_g`` / ``fat_g`` is a **value
    override** (recorded ``user_edit``, marks the item edited); a supplied
    ``amount`` is the adjusted serving count, applied as the
    provenance-preserving servings rescale (``amount_adjust``). Each value is the
    single untrusted number crossing this boundary and is bounds-checked here
    (finite, non-negative) before the confirm service applies the field-specific
    range/rescale rules from ``corrections.py``.
    """

    model_config = ConfigDict(extra="forbid")

    calories: float | None = None
    protein_g: float | None = None
    carbs_g: float | None = None
    fat_g: float | None = None
    #: The adjusted consumed serving count (maps to the food item's ``amount``);
    #: applied as a provenance-preserving rescale, not a value override.
    amount: float | None = None

    @field_validator("calories", "protein_g", "carbs_g", "fat_g", "amount")
    @classmethod
    def _finite_non_negative(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value):
            raise ValueError("value must be a finite number")
        if value < 0:
            raise ValueError("value must be non-negative")
        return value


class LabelProposalResponse(BaseModel):
    """The owner-scoped proposed-values read for a label event (FTY-196).

    ``proposal`` carries the parsed food item (calories, macros, serving) enriched
    with the ``user_label`` ``source`` descriptor so the confirm sheet renders the
    values and their provenance from one DTO. It is ``None`` when the event has no
    uncounted proposal — there is no status oracle, so "already confirmed",
    "never a label", and "not-a-label / unreadable disposition" are all an absent
    proposal.
    """

    model_config = ConfigDict(extra="forbid")

    proposal: DerivedFoodItemDTO | None = None
