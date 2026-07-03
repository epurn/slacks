"""Weight-goal boundary DTOs (FTY-022).

A goal is a user-owned plan: "from ``start_weight_kg`` on ``start_date`` reach
``target_weight_kg`` by ``target_date``." The start snapshot is captured when the
goal is created so the planned trajectory (and therefore the derived daily
target) is deterministic and does not drift as the user's measured weight
changes. Body weight is stored in canonical kilograms; display units are a
separate user preference and never change what is stored.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.enums import ClampReason, GoalDirection, PacePreset, TargetBasis, TargetSource


class GoalCreateRequest(BaseModel):
    """Request to create a weight goal.

    ``start_weight_kg`` and ``start_date`` are the trajectory origin. Callers may
    omit them to default to the user's current weight / today at the service
    boundary; when supplied they pin the plan explicitly. The calculator requires
    a strictly positive horizon, enforced here so an impossible plan is rejected
    at the boundary rather than producing a nonsensical target.
    """

    model_config = ConfigDict(extra="forbid")

    target_weight_kg: float = Field(gt=0, le=1000.0)
    target_date: date
    start_weight_kg: float = Field(gt=0, le=1000.0)
    start_date: date

    @model_validator(mode="after")
    def _check_positive_horizon(self) -> GoalCreateRequest:
        if self.target_date <= self.start_date:
            raise ValueError("target_date must be after start_date")
        return self


class GoalDTO(BaseModel):
    """Response/representation of a persisted goal, built from the ORM row."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    start_weight_kg: float
    start_date: date
    target_weight_kg: float
    target_date: date
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ActiveGoal(BaseModel):
    """The caller's current active goal, summarised for a cold load (FTY-189/FTY-190).

    A goal stores only its trajectory (``start_weight_kg`` / ``target_weight_kg``),
    not ``direction`` or ``pace`` columns, so both are **recovered** from that
    trajectory: ``direction`` from its sign (``target > start`` → ``gain``,
    ``target < start`` → ``loss``, equal → ``maintain``) and ``pace`` as the exact
    inverse of the band the trajectory was derived from (``None`` for ``maintain``
    or an off-grid legacy goal). Trends reads ``direction`` to colour the weight
    delta by progress toward the goal; Settings reads both to summarise a returning
    user's Goal row as direction + pace on a cold launch. Neither field is carried
    in weight, RMR, TDEE, or the calorie target, and pace is a coarse rate preset
    (gentle/steady/faster), not a body number — so this read leaks nothing sensitive.
    """

    model_config = ConfigDict(extra="forbid")

    direction: GoalDirection
    pace: PacePreset | None = None


class GoalTargetRequest(BaseModel):
    """Create/replace the active goal from a direction + pace preset (FTY-106).

    Onboarding collects a *direction* and, for a directional goal, an
    evidence-based *pace preset* — never a free-form numeric rate, so an unsafe
    rate is structurally impossible at the boundary. This contract owns the
    pace→trajectory derivation: direction + pace + start weight become the
    ``(start_weight, target_weight, start_date, target_date)`` the calculator
    consumes (see :mod:`app.services.goals`).

    - ``pace`` is **required** for a ``loss``/``gain`` goal and **ignored** for a
      ``maintain`` goal (maintenance has no rate). ``faster`` is a loss-only
      preset; ``gain`` rejects it.
    - ``start_weight_kg`` defaults to the profile's stored ``weight_kg`` when
      omitted; if neither is available the request is refused.
    - ``start_date`` defaults to today in the profile timezone when omitted.
    """

    model_config = ConfigDict(extra="forbid")

    direction: GoalDirection
    pace: PacePreset | None = None
    start_weight_kg: float | None = Field(default=None, gt=0, le=1000.0)
    start_date: date | None = None

    @model_validator(mode="after")
    def _require_pace_for_directional_goal(self) -> GoalTargetRequest:
        if self.direction is not GoalDirection.MAINTAIN and self.pace is None:
            raise ValueError("pace is required for a loss or gain goal")
        return self


class RevealedTarget(BaseModel):
    """The computed daily target surfaced by the goal endpoint (FTY-106).

    ``calories`` is the derived ``daily_calorie_target_kcal`` (on goal creation
    there is no override, so the effective and derived values coincide). RMR/TDEE
    and ``direction`` come straight from the computed row; ``clamped`` mirrors the
    calculator's safety-clamp flag (the ``clamp`` object carries the reason).
    """

    model_config = ConfigDict(extra="forbid")

    calories: int
    rmr_kcal: float
    tdee_kcal: float
    direction: GoalDirection
    clamped: bool


class TargetProvenance(BaseModel):
    """Where a revealed target came from (FTY-106).

    ``source`` is the shared :class:`~app.enums.TargetSource` discriminator a
    manual override (FTY-095) also uses — a freshly derived target is always
    ``derived``. ``basis`` names what it was derived from. The human line ("from
    your goal + your metrics") is the client's; the API carries the stable tokens.
    """

    model_config = ConfigDict(extra="forbid")

    source: TargetSource
    basis: TargetBasis


class ClampStatus(BaseModel):
    """Honest surfacing of the calculator's safety clamp (FTY-106).

    When the derived plan was clamped to a safety boundary, ``clamped`` is true and
    ``reason`` names the boundary so the reveal can show a calm note instead of
    presenting the boundary value as the achievable plan. ``reason`` is ``null``
    when the target was within the safe band.
    """

    model_config = ConfigDict(extra="forbid")

    clamped: bool
    reason: ClampReason | None


class GoalTargetResponse(BaseModel):
    """Combined goal + computed-target reveal (FTY-106).

    The single response the target reveal and Profile render: the persisted active
    ``goal``, the computed ``target``, its ``provenance``, and the ``clamp`` status.
    """

    model_config = ConfigDict(extra="forbid")

    goal: GoalDTO
    target: RevealedTarget
    provenance: TargetProvenance
    clamp: ClampStatus
