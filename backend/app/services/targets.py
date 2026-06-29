"""Target service: derive, persist, and manually override daily targets.

Ties the profile (body constants) and a goal (the weight trajectory) to the
deterministic calculator, then persists the result as a user-owned
``daily_targets`` row (FTY-022/FTY-094). On top of that derived value this module
owns the **manual override** lifecycle (FTY-095): a user may set an explicit
calorie and/or macro target and reset it back to the derived value, with the
read-model honestly reporting ``derived`` vs ``user`` provenance per target.

Every access path is object-level authorized and fails closed: a caller may only
touch targets for *their own* goal. Target numbers are sensitive derived body
data and are never logged — only user/goal ids appear in any diagnostic.

Override lifecycle (the documented invariant, see ``target-calculator.md``):

- The override lives on ``daily_targets`` beside the derived columns. The
  effective value is a pure read-time ``override ?? derived``.
- A derived **recompute** (goal/pace/metric edit) refreshes the derived columns in
  place and **leaves any in-force override untouched**; when a recompute
  materialises a row for a *new* date it carries the goal's in-force override
  forward so the choice does not silently lapse on a date rollover.
- An override is cleared **only** by an explicit reset or by deletion/replacement
  of the owning goal (``ON DELETE CASCADE`` from ``goal_id``).
- A manual override is validated against the documented safety band and an
  out-of-band value is **rejected** (not silently clamped like the derived path):
  the user's explicit number is refused honestly, never quietly altered.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import MetabolicFormula, OverridableTarget
from app.estimator import compute_targets, constants
from app.models.identity import User, UserProfile
from app.models.targets import DailyTarget, Goal
from app.schemas.targets import (
    TargetCalculatorInput,
    TargetCalculatorResult,
    TargetComponent,
    TargetOverrideRequest,
    TargetReadModel,
)
from app.timeutils import user_timezone


class GoalForbidden(Exception):
    """Raised when a caller tries to act on a goal they do not own."""


class TargetNotFound(Exception):
    """Raised when no overridable target row exists for the caller's active goal.

    Rendered as the same fail-closed ``404`` as :class:`GoalForbidden` so a
    cross-user caller and a caller with no active goal / no stored target are
    indistinguishable (no existence oracle).
    """


class OverrideOutOfBand(Exception):
    """Raised when a manual override falls outside its documented safety band.

    Carries the offending field and the band so the router can return a clear
    ``422`` — the user sees their value refused, not silently clamped.
    """

    def __init__(self, field: str, value: int, low: int, high: int) -> None:
        super().__init__(f"{field} override {value} is outside the allowed band [{low}, {high}]")
        self.field = field
        self.value = value
        self.low = low
        self.high = high


class IncompleteProfileError(Exception):
    """Raised when the profile is missing a field the calculator requires."""


def _utcnow() -> datetime:
    """Timezone-aware UTC now (override audit stamp)."""

    return datetime.now(UTC)


def derive_age_years(birth_year: int, on_date: date) -> int:
    """Whole-year age on ``on_date``.

    The profile stores only ``birth_year`` (privacy-minimal — no birth month/day),
    so age is a whole-year approximation. Documented assumption, exercised by
    tests.
    """

    return on_date.year - birth_year


def build_calculator_input(
    profile: UserProfile, goal: Goal, *, for_date: date
) -> TargetCalculatorInput:
    """Assemble a validated calculator input from a profile and goal.

    Raises :class:`IncompleteProfileError` if the profile has not captured the
    body metrics the math needs, so an incomplete profile can never silently
    produce a bogus target.
    """

    if profile.height_m is None or profile.birth_year is None:
        raise IncompleteProfileError("profile is missing height or birth year")

    formula = MetabolicFormula(profile.metabolic_formula)
    if formula is MetabolicFormula.MIFFLIN_ST_JEOR:
        # The unspecified family default carries no RMR constant: a profile that
        # has not yet captured a +5/-161 variant cannot produce a target.
        raise IncompleteProfileError("profile has not selected a metabolic formula variant")

    return TargetCalculatorInput(
        metabolic_formula=formula,
        height_m=profile.height_m,
        age_years=derive_age_years(profile.birth_year, for_date),
        start_weight_kg=goal.start_weight_kg,
        target_weight_kg=goal.target_weight_kg,
        start_date=goal.start_date,
        target_date=goal.target_date,
    )


def compute_daily_target(
    session: Session,
    owner_id: uuid.UUID,
    goal_id: uuid.UUID,
    current_user: User,
    *,
    for_date: date,
) -> DailyTarget:
    """Compute and persist (or recompute) a daily target for ``owner_id``'s goal.

    Enforces that ``current_user`` owns the goal (fail closed), computes the
    deterministic target, and upserts it as a user-owned ``daily_targets`` row.

    Recompute discipline (FTY-095): if a row already exists for ``(goal, for_date)``
    its **derived** columns are refreshed in place and any in-force **override**
    columns are left untouched. When a row is materialised for a *new* date, the
    goal's most recent in-force override is carried forward onto it so a manual
    choice does not lapse on a date rollover.
    """

    _authorize(owner_id, current_user)
    goal = session.get(Goal, goal_id)
    if goal is None or goal.user_id != owner_id:
        # No existence oracle: an unowned or missing goal looks the same.
        raise GoalForbidden("goal not found for this user")

    profile = session.scalars(
        select(UserProfile).where(UserProfile.user_id == owner_id)
    ).one_or_none()
    if profile is None:
        raise IncompleteProfileError("profile not found")

    payload = build_calculator_input(profile, goal, for_date=for_date)
    result = compute_targets(payload)

    record = session.scalars(
        select(DailyTarget).where(
            DailyTarget.goal_id == goal_id,
            DailyTarget.for_date == for_date,
        )
    ).one_or_none()
    if record is None:
        record = DailyTarget(user_id=owner_id, goal_id=goal_id, for_date=for_date)
        _carry_forward_override(session, goal_id, record)
        session.add(record)
    _apply_derived(record, payload, result)
    session.commit()
    session.refresh(record)
    return record


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

    _authorize(owner_id, current_user)
    day = _resolve_day(session, owner_id, for_date)
    return _resolve_carried_target(session, owner_id, day)


def set_target_override(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    request: TargetOverrideRequest,
    *,
    for_date: date | None = None,
) -> DailyTarget:
    """Record a calorie and/or macro override on the active goal's target.

    Object-level authorized (fail closed); ``for_date`` defaults to today in the
    owner's profile timezone. When no exact-date row exists yet but the owner has an
    active goal covering the day, the row is **materialised on demand** (via
    :func:`compute_daily_target`, carrying any in-force override forward) so an
    override succeeds on any in-horizon day, not just goal-creation day. Because that
    materialisation runs the calculator, a profile that has gone incomplete raises
    :class:`IncompleteProfileError` (``409``). Each provided value is validated against
    its documented safety band and an out-of-band value raises
    :class:`OverrideOutOfBand` (``422``) with nothing persisted. On success the
    targeted override columns are set, ``override_set_at`` is stamped, and the
    updated row is returned with the overridden targets reporting ``source: user``.
    """

    _authorize(owner_id, current_user)
    day = _resolve_day(session, owner_id, for_date)
    target = _resolve_or_materialise_target(session, owner_id, current_user, day)

    _validate_override(target, request)

    if request.calorie_target_kcal is not None:
        target.override_calorie_target_kcal = request.calorie_target_kcal
    if request.protein_target_g is not None:
        target.override_protein_target_g = request.protein_target_g
    if request.carbs_target_g is not None:
        target.override_carbs_target_g = request.carbs_target_g
    if request.fat_target_g is not None:
        target.override_fat_target_g = request.fat_target_g
    target.override_set_at = _utcnow()

    session.commit()
    session.refresh(target)
    return target


def reset_target_override(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    targets: list[OverridableTarget] | None,
    *,
    for_date: date | None = None,
) -> DailyTarget:
    """Clear the targeted override column(s) back to ``NULL`` (reset to derived).

    Object-level authorized (fail closed); ``for_date`` defaults to today in the
    owner's profile timezone. When no exact-date row exists yet but the owner has an
    active goal covering the day, the row is **materialised on demand** (via
    :func:`compute_daily_target`, carrying any in-force override forward), then the
    reset is applied to it — so a reset succeeds on any in-horizon day. Because that
    materialisation runs the calculator, a profile that has gone incomplete raises
    :class:`IncompleteProfileError` (``409``). ``targets``
    names which overrides to clear; ``None`` or an empty list clears **all** in-force
    overrides. Resetting a target that is already derived is a no-op. After the last
    in-force override is cleared, ``override_set_at`` is cleared too. The cleared
    targets fall back to the derived value with ``source: derived``.
    """

    _authorize(owner_id, current_user)
    day = _resolve_day(session, owner_id, for_date)
    target = _resolve_or_materialise_target(session, owner_id, current_user, day)

    to_clear = set(targets) if targets else set(OverridableTarget)
    if OverridableTarget.CALORIES in to_clear:
        target.override_calorie_target_kcal = None
    if OverridableTarget.PROTEIN in to_clear:
        target.override_protein_target_g = None
    if OverridableTarget.CARBS in to_clear:
        target.override_carbs_target_g = None
    if OverridableTarget.FAT in to_clear:
        target.override_fat_target_g = None

    if not _has_override(target):
        target.override_set_at = None

    session.commit()
    session.refresh(target)
    return target


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


def _authorize(owner_id: uuid.UUID, current_user: User) -> None:
    """Fail closed unless ``current_user`` owns ``owner_id``'s data."""

    if owner_id != current_user.id:
        raise GoalForbidden("cross-user goal access denied")


def _resolve_day(session: Session, owner_id: uuid.UUID, for_date: date | None) -> date:
    """Return ``for_date``, or today in the owner's profile timezone when omitted.

    Mirrors the daily-summary day-default rule so a manual override lands on the
    same ``(active goal, for_date)`` row the summary reads. Falls back to UTC when
    the profile has no timezone.
    """

    if for_date is not None:
        return for_date
    tz = user_timezone(session, owner_id)
    return datetime.now(tz).date()


def _resolve_active_target_row(
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
    :func:`_resolve_or_materialise_target`, which materialises the exact-date row when
    it is missing but in horizon; the read paths use :func:`resolve_carried_target_row`
    instead.
    """

    target = _resolve_active_target_row(session, owner_id, for_date)
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


def _resolve_or_materialise_target(
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

    target = _resolve_active_target_row(session, owner_id, for_date)
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


def _validate_override(target: DailyTarget, request: TargetOverrideRequest) -> None:
    """Reject any provided override that falls outside its documented band.

    The calorie band is the exact safety band the row was derived against (read
    from its assumptions snapshot — floor 1500/1200 kcal by variant, ceiling 4000).
    Each macro band reuses that calorie ceiling and the Atwater factors as a sanity
    bound (FTY-094 documents no separate per-macro clinical band): a non-negative
    whole-gram target whose energy cannot exceed the calorie ceiling. No new
    numbers are introduced. Raises :class:`OverrideOutOfBand` on the first failure
    so nothing is persisted.
    """

    floor = int(target.assumptions["safety_floor_kcal"])
    ceiling = int(target.assumptions["safety_ceiling_kcal"])

    if request.calorie_target_kcal is not None:
        _check_band("calorie_target_kcal", request.calorie_target_kcal, floor, ceiling)
    if request.protein_target_g is not None:
        _check_band(
            "protein_target_g",
            request.protein_target_g,
            0,
            ceiling // constants.KCAL_PER_G_PROTEIN,
        )
    if request.carbs_target_g is not None:
        _check_band(
            "carbs_target_g",
            request.carbs_target_g,
            0,
            ceiling // constants.KCAL_PER_G_CARB,
        )
    if request.fat_target_g is not None:
        _check_band(
            "fat_target_g",
            request.fat_target_g,
            0,
            ceiling // constants.KCAL_PER_G_FAT,
        )


def _check_band(field: str, value: int, low: int, high: int) -> None:
    if value < low or value > high:
        raise OverrideOutOfBand(field, value, low, high)


def _has_override(target: DailyTarget) -> bool:
    """True when any override column on ``target`` is still set."""

    return any(
        column is not None
        for column in (
            target.override_calorie_target_kcal,
            target.override_protein_target_g,
            target.override_carbs_target_g,
            target.override_fat_target_g,
        )
    )


def _carry_forward_override(session: Session, goal_id: uuid.UUID, record: DailyTarget) -> None:
    """Copy the goal's most recent in-force override onto a new-date target row.

    Keeps a manual choice alive across a date rollover: the override persists until
    reset or goal deletion, independent of which ``for_date`` row materialises.
    """

    previous = session.scalars(
        select(DailyTarget)
        .where(DailyTarget.goal_id == goal_id)
        .order_by(DailyTarget.created_at.desc())
    ).first()
    if previous is None or not _has_override(previous):
        return
    record.override_calorie_target_kcal = previous.override_calorie_target_kcal
    record.override_protein_target_g = previous.override_protein_target_g
    record.override_carbs_target_g = previous.override_carbs_target_g
    record.override_fat_target_g = previous.override_fat_target_g
    record.override_set_at = previous.override_set_at


def _apply_derived(
    record: DailyTarget,
    payload: TargetCalculatorInput,
    result: TargetCalculatorResult,
) -> None:
    """Write the derived columns from a fresh calculation, leaving overrides alone."""

    record.rmr_kcal = result.rmr_kcal
    record.tdee_kcal = result.tdee_kcal
    record.daily_calorie_target_kcal = result.daily_calorie_target_kcal
    record.clamped = result.clamped
    record.protein_target_g = result.protein_target_g
    record.carbs_target_g = result.carbs_target_g
    record.fat_target_g = result.fat_target_g
    record.macros_clamped = result.macros_clamped
    record.inputs = payload.model_dump(mode="json")
    record.assumptions = result.assumptions.model_dump(mode="json")
