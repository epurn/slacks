"""Goals service: create the active goal from direction + pace, reveal its target (FTY-106).

This module owns the one piece of math that sits between onboarding's inputs and
the FTY-022 calculator: turning a **direction** + an evidence-based **pace
preset** + a **start weight** into the concrete
``(start_weight, target_weight, start_date, target_date)`` trajectory the
calculator consumes. The pace vocabulary, the safe-pace bands, and the fixed
planning horizon are this contract's responsibility — not the client's, and not
the calculator's.

The flow:

1. Resolve the start weight (request, else the profile's stored weight) and start
   date (request, else today in the profile timezone).
2. Derive the trajectory deterministically from direction + pace over a fixed
   planning horizon (:data:`PLANNING_HORIZON_WEEKS`).
3. Replace any prior active goal (one active goal per user) and persist the new
   one, then call the **existing** ``compute_daily_target`` (FTY-022) to compute
   and persist today's ``daily_targets`` row — never re-deriving the NIDDK math.

Every access path is object-level authorized and fails closed: a caller may only
create a goal for *their own* ``user_id``. Weight, RMR, TDEE, and the target are
sensitive derived body data and are never logged — only ids appear in diagnostics.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from math import isclose
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import ClampReason, GoalDirection, PacePreset, TargetBasis, TargetSource
from app.models.identity import User, UserProfile
from app.models.targets import DailyTarget, Goal
from app.schemas.goals import (
    ClampStatus,
    GoalDTO,
    GoalTargetRequest,
    GoalTargetResponse,
    RevealedTarget,
    TargetProvenance,
)
from app.services.targets import (
    GoalForbidden,
    IncompleteProfileError,
    build_calculator_input,
    compute_daily_target,
)
from app.timeutils import current_day

#: Fixed planning horizon, in weeks, over which a pace (a rate) is projected into a
#: destination weight and date. Onboarding captures pace but not a goal weight, so
#: the endpoint synthesizes a destination over this horizon: it is the load-bearing
#: product choice that scales the rate into ``target_weight`` / ``target_date``.
#: 12 weeks is a defensible, conventional planning block; documented here as the
#: single named constant so the derivation stays deterministic and explainable.
PLANNING_HORIZON_WEEKS = 12

#: The recommended default pace preset. Onboarding pre-selects steady (~0.5%/wk
#: loss, ~0.25%/wk gain); the server still requires an explicit pace for a
#: directional goal, but this names the evidence-based default the UI offers.
DEFAULT_PACE = PacePreset.STEADY

#: Weekly weight-change rate as a fraction of start weight, by direction + preset.
#:
#: Evidence-grounded (overriding the generic "faster is better" default): a safe,
#: lean-mass-sparing loss rate is ~0.5–1%/wk (≈ the NIH/NIDDK ~500–1000 kcal/day
#: deficit); above ~1.5%/wk measurably increases lean-mass loss, so no loss preset
#: exceeds 1%/wk and steady (0.5%/wk) is the default. Lean gain is far slower
#: (~0.125–0.25%/wk), and there is no "faster" gain preset. ``maintain`` has no
#: rate (handled separately). The calculator's safety floor/ceiling remains the
#: hard backstop that clamps and flags an over-aggressive derived plan.
PACE_WEEKLY_FRACTION: dict[GoalDirection, dict[PacePreset, float]] = {
    GoalDirection.LOSS: {
        PacePreset.GENTLE: 0.0025,  # ~0.25%/wk
        PacePreset.STEADY: 0.005,  # ~0.5%/wk (default)
        PacePreset.FASTER: 0.01,  # ~1%/wk (cap; never the default)
    },
    GoalDirection.GAIN: {
        PacePreset.GENTLE: 0.00125,  # ~0.125%/wk
        PacePreset.STEADY: 0.0025,  # ~0.25%/wk (default)
    },
}


class InvalidPace(Exception):
    """Raised when a pace preset is not valid for the chosen direction.

    The pace enum value is itself well-formed (so the Pydantic boundary accepts
    it), but the combination is not offered — e.g. ``faster`` for a ``gain`` goal.
    Rendered as ``422`` by the router.
    """


class Trajectory(NamedTuple):
    """The deterministic weight trajectory derived from direction + pace.

    The four fields the calculator consumes. ``start_weight_kg`` / ``start_date``
    are pass-throughs of the resolved inputs; ``target_weight_kg`` / ``target_date``
    are derived over :data:`PLANNING_HORIZON_WEEKS`.
    """

    start_weight_kg: float
    target_weight_kg: float
    start_date: date
    target_date: date


def derive_trajectory(
    direction: GoalDirection,
    pace: PacePreset | None,
    start_weight_kg: float,
    start_date: date,
) -> Trajectory:
    """Derive the goal trajectory from direction + pace (pure and deterministic).

    ``rate_kg_per_week = pace_fraction × start_weight_kg``; the destination is that
    rate projected over :data:`PLANNING_HORIZON_WEEKS` (subtracted for ``loss``,
    added for ``gain``). ``maintain`` ignores ``pace`` and yields
    ``target_weight == start_weight`` (the calculator's ``wT == w0 → TDEE`` path).
    The horizon gives a strictly positive ``target_date > start_date``.

    Raises :class:`InvalidPace` if ``pace`` is not offered for ``direction``.
    """

    target_date = start_date + timedelta(weeks=PLANNING_HORIZON_WEEKS)

    if direction is GoalDirection.MAINTAIN:
        return Trajectory(start_weight_kg, start_weight_kg, start_date, target_date)

    bands = PACE_WEEKLY_FRACTION[direction]
    if pace is None or pace not in bands:
        raise InvalidPace(f"pace {pace!r} is not valid for a {direction} goal")

    delta_kg = bands[pace] * start_weight_kg * PLANNING_HORIZON_WEEKS
    if direction is GoalDirection.LOSS:
        target_weight_kg = start_weight_kg - delta_kg
    else:
        target_weight_kg = start_weight_kg + delta_kg
    return Trajectory(start_weight_kg, target_weight_kg, start_date, target_date)


def create_goal_with_target(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    request: GoalTargetRequest,
) -> tuple[Goal, DailyTarget]:
    """Create/replace the active goal from direction + pace and compute its target.

    Object-level authorized (fail closed). Resolves the start weight/date, derives
    the trajectory, deactivates any prior active goal, persists the new active
    goal, and calls the existing ``compute_daily_target`` to compute and persist
    today's ``daily_targets`` row — all in one committed transaction, so a
    subsequent ``GET daily-summary`` for today finds a non-``null`` target.

    Raises :class:`GoalForbidden` on cross-user access; :class:`IncompleteProfileError`
    when the profile cannot produce a target (no resolvable weight, missing
    height/birth year, or formula still on the unspecified family default);
    :class:`InvalidPace` when the pace is not offered for the direction. Validation
    happens before any mutation so a failure never half-creates a goal.
    """

    _authorize(owner_id, current_user)

    profile = session.scalars(
        select(UserProfile).where(UserProfile.user_id == owner_id)
    ).one_or_none()
    if profile is None:
        raise IncompleteProfileError("profile not found")

    start_weight_kg = (
        request.start_weight_kg if request.start_weight_kg is not None else profile.weight_kg
    )
    if start_weight_kg is None:
        raise IncompleteProfileError(
            "no start weight: the profile has no stored weight and none was provided"
        )

    today = current_day(session, owner_id)
    start_date = request.start_date if request.start_date is not None else today

    trajectory = derive_trajectory(request.direction, request.pace, start_weight_kg, start_date)
    goal = Goal(
        user_id=owner_id,
        start_weight_kg=trajectory.start_weight_kg,
        start_date=trajectory.start_date,
        target_weight_kg=trajectory.target_weight_kg,
        target_date=trajectory.target_date,
        is_active=True,
    )

    # Validate the calculator input *before* mutating, so an incomplete profile
    # raises without leaving a half-created goal behind.
    build_calculator_input(profile, goal, for_date=today)

    # One active goal per user: deactivate any prior active goal, then insert the
    # new one. ``compute_daily_target`` commits, so the deactivation, the new goal,
    # and the new target land in a single transaction.
    for prior in session.scalars(
        select(Goal).where(Goal.user_id == owner_id, Goal.is_active.is_(True))
    ).all():
        prior.is_active = False
    session.add(goal)
    session.flush()

    target = compute_daily_target(session, owner_id, goal.id, current_user, for_date=today)
    session.refresh(goal)
    return goal, target


def direction_of(goal: Goal) -> GoalDirection:
    """Recover a goal's direction from its persisted trajectory (FTY-189).

    A goal has no stored ``direction`` column — it is a pure function of the start
    vs. target weight the trajectory was derived from: ``target > start`` is a
    ``gain`` plan, ``target < start`` a ``loss`` plan, and ``target == start`` (the
    exact ``maintain`` path in :func:`derive_trajectory`) a ``maintain`` plan.
    """

    if goal.target_weight_kg > goal.start_weight_kg:
        return GoalDirection.GAIN
    if goal.target_weight_kg < goal.start_weight_kg:
        return GoalDirection.LOSS
    return GoalDirection.MAINTAIN


def pace_of(goal: Goal) -> PacePreset | None:
    """Recover the pace preset from a persisted trajectory when it matches one.

    The write endpoint persists only the derived start/target weights and dates.
    Because the derivation uses a fixed horizon and named pace fractions, a goal
    created by this service can be projected back to its preset. Maintenance has
    no pace, and old/manual trajectories that do not match a known preset return
    ``None`` rather than guessing.
    """

    direction = direction_of(goal)
    if direction is GoalDirection.MAINTAIN:
        return None

    days = (goal.target_date - goal.start_date).days
    if days <= 0 or goal.start_weight_kg <= 0:
        return None

    weeks = days / 7
    observed_fraction = (
        abs(goal.target_weight_kg - goal.start_weight_kg) / goal.start_weight_kg / weeks
    )
    for preset, expected_fraction in PACE_WEEKLY_FRACTION[direction].items():
        if isclose(observed_fraction, expected_fraction, rel_tol=1e-6, abs_tol=1e-9):
            return preset
    return None


def read_active_goal(session: Session, owner_id: uuid.UUID, current_user: User) -> Goal | None:
    """Return the caller's single active goal, or ``None`` when there is none.

    Object-level authorized and fail-closed: a caller may only read *their own*
    active goal. Raises :class:`GoalForbidden` on cross-user access (the router
    maps both that and "no active goal" to ``404`` so the two are indistinguishable
    — no existence oracle, exactly as goal creation fails closed).
    """

    _authorize(owner_id, current_user)
    return session.scalars(
        select(Goal).where(Goal.user_id == owner_id, Goal.is_active.is_(True))
    ).one_or_none()


def build_goal_target_response(
    goal: Goal, target: DailyTarget, direction: GoalDirection
) -> GoalTargetResponse:
    """Project a persisted goal + computed target into the reveal response.

    ``calories`` is the derived target (no override exists on a fresh goal). The
    provenance marks the number as ``derived`` from ``goal_and_metrics``; the clamp
    status surfaces the calculator's safety clamp honestly.
    """

    return GoalTargetResponse(
        goal=GoalDTO.model_validate(goal),
        target=RevealedTarget(
            calories=target.daily_calorie_target_kcal,
            rmr_kcal=target.rmr_kcal,
            tdee_kcal=target.tdee_kcal,
            direction=direction,
            clamped=target.clamped,
        ),
        provenance=TargetProvenance(
            source=TargetSource.DERIVED, basis=TargetBasis.GOAL_AND_METRICS
        ),
        clamp=_clamp_status(target),
    )


def _authorize(owner_id: uuid.UUID, current_user: User) -> None:
    """Fail closed unless ``current_user`` owns ``owner_id``'s data."""

    if owner_id != current_user.id:
        raise GoalForbidden("cross-user goal access denied")


def _clamp_status(target: DailyTarget) -> ClampStatus:
    """Surface which safety boundary (if any) the derived target was clamped to.

    The calculator stores only a boolean ``clamped``; the boundary is recovered
    from the value itself — a clamped target equals exactly the floor or the
    ceiling from its own assumptions snapshot.
    """

    if not target.clamped:
        return ClampStatus(clamped=False, reason=None)
    floor = int(target.assumptions["safety_floor_kcal"])
    reason = (
        ClampReason.CLAMPED_TO_FLOOR
        if target.daily_calorie_target_kcal <= floor
        else ClampReason.CLAMPED_TO_CEILING
    )
    return ClampStatus(clamped=True, reason=reason)
