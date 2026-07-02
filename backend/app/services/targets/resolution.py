"""Active and carried-forward target resolution.

Which ``daily_targets`` row answers a request for ``(owner, day)`` — and how a
missing row is handled — differs between reads and writes (see the
"Target resolution" section of ``target-calculator.md``):

- **Reads carry forward.** A row is stored only on goal-creation day, but the
  daily target is effectively constant across the goal's horizon, so a read
  resolves the *most recent stored row at or before* the day while it is within
  the horizon (:func:`resolve_carried_target_row`).
- **Override writes need the exact-date row**, materialising it on demand when the
  owner has an active goal covering the day
  (:func:`resolve_or_materialise_target`).

Both fail closed with :class:`TargetNotFound` (the router's ``404``) so a
cross-user caller and a caller with no in-horizon row are indistinguishable — no
existence oracle.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import User
from app.models.targets import DailyTarget, Goal
from app.timeutils import current_day

from .access import authorize
from .derivation import compute_daily_target
from .errors import TargetNotFound


def get_active_target(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    *,
    for_date: date | None = None,
) -> DailyTarget:
    """Return the active goal's target for ``owner_id`` on ``for_date``.

    ``for_date`` defaults to the current day in the owner's profile timezone
    (resolved only after authorization, so a cross-user caller learns nothing). The
    target is **carried forward** within the goal's horizon: because the daily
    target is constant across the horizon and a row is only stored on goal-creation
    day, any in-horizon day reads the most recent stored row (see
    :func:`resolve_carried_target_row`). Fails closed: cross-user access raises
    :class:`GoalForbidden`; no active goal, a day before the goal's first row, or a
    day past the horizon raises :class:`TargetNotFound`. Both map to the router's
    ``404`` so neither confirms another user's data nor a missing row.
    """

    authorize(owner_id, current_user)
    day = resolve_day(session, owner_id, for_date)
    return _resolve_carried_target(session, owner_id, day)


def resolve_day(session: Session, owner_id: uuid.UUID, for_date: date | None) -> date:
    """Return ``for_date``, or today in the owner's profile timezone when omitted.

    Mirrors the daily-summary day-default rule so a manual override lands on the
    same ``(active goal, for_date)`` row the summary reads. Falls back to UTC when
    the profile has no timezone.
    """

    if for_date is not None:
        return for_date
    return current_day(session, owner_id)


def resolve_active_target_row(
    session: Session, owner_id: uuid.UUID, for_date: date
) -> DailyTarget | None:
    """Load the active goal's target row for ``owner_id`` on ``for_date``, or None.

    This is the shared query predicate for the active-goal target lookup, used by
    both the override endpoints (targets service) and the daily-summary endpoint.
    Each caller applies its own not-found policy and return shape: the targets
    service raises, daily_summary returns None and projects to the read-model.
    """

    return session.scalars(
        select(DailyTarget)
        .join(Goal, DailyTarget.goal_id == Goal.id)
        .where(
            DailyTarget.user_id == owner_id,
            Goal.user_id == owner_id,
            Goal.is_active.is_(True),
            DailyTarget.for_date == for_date,
        )
    ).one_or_none()


def _resolve_active_target(session: Session, owner_id: uuid.UUID, for_date: date) -> DailyTarget:
    """Load the active goal's **exact-date** target row for ``owner_id``.

    Raises :class:`TargetNotFound` when the user has no active goal or no stored
    target row for *that exact day* — the same fail-closed signal as a cross-user
    attempt. The override write paths layer on this via
    :func:`resolve_or_materialise_target`, which materialises the exact-date row when
    it is missing but in horizon; the read paths use :func:`resolve_carried_target_row`
    instead.
    """

    target = resolve_active_target_row(session, owner_id, for_date)
    if target is None:
        raise TargetNotFound("no active target for this user and day")
    return target


def _active_goal_covering(session: Session, owner_id: uuid.UUID, for_date: date) -> Goal | None:
    """The owner's active goal whose planned horizon covers ``for_date``, or None.

    A goal covers ``for_date`` when ``start_date <= for_date <= target_date`` — the
    same ``[start_date, target_date]`` horizon the read carry-forward bounds against.
    Returns ``None`` when there is no active goal or the day falls outside its
    horizon, so the write path can fail closed without an existence oracle.
    """

    return session.scalars(
        select(Goal).where(
            Goal.user_id == owner_id,
            Goal.is_active.is_(True),
            Goal.start_date <= for_date,
            Goal.target_date >= for_date,
        )
    ).one_or_none()


def resolve_or_materialise_target(
    session: Session, owner_id: uuid.UUID, current_user: User, for_date: date
) -> DailyTarget:
    """Resolve the exact-date target row for an override write, materialising on demand.

    An override must land on a **concrete** row for the requested day, never on a
    carried-forward earlier row. A ``daily_targets`` row is only stored on
    goal-creation day (and on a prior override write), so a later in-horizon day has
    no row yet: when the owner has an active goal whose horizon covers ``for_date`` we
    materialise the row via :func:`compute_daily_target` (which creates it, carries any
    in-force override forward, and applies the fresh derived columns), then return it.
    With no active goal covering the day we fail closed with :class:`TargetNotFound`
    (``404``), indistinguishable from a cross-user attempt — no existence oracle.
    """

    target = resolve_active_target_row(session, owner_id, for_date)
    if target is not None:
        return target
    goal = _active_goal_covering(session, owner_id, for_date)
    if goal is None:
        raise TargetNotFound("no active target for this user and day")
    return compute_daily_target(session, owner_id, goal.id, current_user, for_date=for_date)


def resolve_carried_target_row(
    session: Session, owner_id: uuid.UUID, for_date: date
) -> DailyTarget | None:
    """Most-recent active-goal target row at or before ``for_date``, within horizon.

    A ``daily_targets`` row is only materialised on goal-creation day (and on an
    override write), so an exact-date lookup misses every later day — which wrongly
    made the target (and, via the onboarding gate, the user's onboarded state)
    vanish from the day after onboarding onward. But the dynamic-energy-balance
    model yields a **constant daily intake across a goal's horizon**:
    ``compute_daily_target`` derives from the goal's fixed ``(start_weight,
    target_weight, start_date, target_date)`` snapshot and ``for_date`` enters only
    through whole-year age, so for any in-horizon day the most recent stored row
    carries the correct target forward.

    Returns the newest active-goal :class:`DailyTarget` with ``for_date <=`` the
    requested day while that day is on or before the goal's ``target_date`` (within
    the planned horizon), else ``None`` — the caller fails closed (``404``) or
    renders ``null``. Days before the first stored row, days past ``target_date``
    (a completed trajectory; the user is steered to set a new goal rather than shown
    a stale deficit), no active goal, and cross-user all resolve to ``None``.
    """

    return session.scalars(
        select(DailyTarget)
        .join(Goal, DailyTarget.goal_id == Goal.id)
        .where(
            DailyTarget.user_id == owner_id,
            Goal.user_id == owner_id,
            Goal.is_active.is_(True),
            Goal.target_date >= for_date,
            DailyTarget.for_date <= for_date,
        )
        .order_by(DailyTarget.for_date.desc())
        .limit(1)
    ).one_or_none()


def _resolve_carried_target(session: Session, owner_id: uuid.UUID, for_date: date) -> DailyTarget:
    """Carry-forward read resolver: like :func:`_resolve_active_target` but returns
    the most recent in-horizon row (see :func:`resolve_carried_target_row`).

    Raises :class:`TargetNotFound` (fail-closed ``404``) when there is no in-horizon
    row to carry — no active goal, a day before the goal's first row, or a day past
    the horizon — indistinguishable from a cross-user attempt (no existence oracle).
    """

    target = resolve_carried_target_row(session, owner_id, for_date)
    if target is None:
        raise TargetNotFound("no active target for this user and day")
    return target
