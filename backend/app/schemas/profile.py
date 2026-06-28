"""User profile boundary DTOs (FTY-020).

The profile DTO and the update-request shape are contracts consumed by mobile
(FTY-021) and the target calculator (FTY-022). Body metrics are expressed in
canonical units (height in metres, weight in kilograms); ``units_preference`` is
the display choice only and never changes stored values.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from zoneinfo import available_timezones

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.enums import MetabolicFormula, UnitsPreference

#: Cached set of valid IANA timezone names for boundary validation.
_VALID_TIMEZONES = available_timezones()


def _validate_timezone(value: str) -> str:
    """Reject anything that is not a known IANA timezone name."""

    if value not in _VALID_TIMEZONES:
        raise ValueError("unknown IANA timezone")
    return value


class ProfileDTO(BaseModel):
    """Response body for the profile read/write API.

    Built directly from the :class:`~app.models.identity.UserProfile` ORM row.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    height_m: float | None
    weight_kg: float | None
    birth_year: int | None
    metabolic_formula: MetabolicFormula
    units_preference: UnitsPreference
    timezone: str
    updated_at: datetime


class ProfileUpdateRequest(BaseModel):
    """Request body for ``PUT /api/users/{user_id}/profile``.

    A partial update: only fields present in the request are applied (see the
    profile service), so a client can capture metrics incrementally. Bounds keep
    physically implausible body metrics out of the store; FTY-021 may tighten
    them further.

    ``metabolic_formula``, ``units_preference``, and ``timezone`` back NOT NULL
    columns and are therefore required when present — an explicit ``null`` is
    rejected with 422.  Absent (unset) still means "leave untouched".
    ``height_m``, ``weight_kg``, and ``birth_year`` back nullable columns and
    continue to accept absent and null values.
    """

    model_config = ConfigDict(extra="forbid")

    height_m: float | None = Field(default=None, gt=0, le=3.0)
    weight_kg: float | None = Field(default=None, gt=0, le=1000.0)
    birth_year: int | None = Field(default=None, ge=1900, le=2100)
    metabolic_formula: MetabolicFormula | None = None
    units_preference: UnitsPreference | None = None
    timezone: str | None = Field(default=None, max_length=64)

    @field_validator("metabolic_formula", "units_preference", "timezone", mode="before")
    @classmethod
    def _reject_explicit_null(cls, v: object) -> object:
        """Reject an explicit null on fields that back NOT NULL columns.

        Absent (unset) fields bypass this validator and use the default; only a
        JSON ``null`` that was actually present in the request reaches here.
        """
        if v is None:
            raise ValueError("field cannot be null when provided")
        return v

    _check_timezone = field_validator("timezone")(_validate_timezone)
