"""Manual override lifecycle (FTY-095): set and reset a target's overrides.

On top of the derived value, a user may set an explicit calorie and/or macro
target and reset it back to the derived value. Both write paths resolve the
exact-date row (materialising it on demand within the horizon — see
:mod:`.resolution`), validate against the documented safety band (reject, never
clamp — see :mod:`.override_rules`), and leave the read-model honestly reporting
``derived`` vs ``user`` provenance per target.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from app.enums import OverridableTarget
from app.models.identity import User
from app.models.targets import DailyTarget
from app.schemas.targets import TargetOverrideRequest

from .access import authorize
from .override_rules import has_override, validate_override
from .resolution import resolve_day, resolve_or_materialise_target


def _utcnow() -> datetime:
    """Timezone-aware UTC now (override audit stamp)."""

    return datetime.now(UTC)


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

    authorize(owner_id, current_user)
    day = resolve_day(session, owner_id, for_date)
    target = resolve_or_materialise_target(session, owner_id, current_user, day)

    validate_override(target, request)

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

    authorize(owner_id, current_user)
    day = resolve_day(session, owner_id, for_date)
    target = resolve_or_materialise_target(session, owner_id, current_user, day)

    to_clear = set(targets) if targets else set(OverridableTarget)
    if OverridableTarget.CALORIES in to_clear:
        target.override_calorie_target_kcal = None
    if OverridableTarget.PROTEIN in to_clear:
        target.override_protein_target_g = None
    if OverridableTarget.CARBS in to_clear:
        target.override_carbs_target_g = None
    if OverridableTarget.FAT in to_clear:
        target.override_fat_target_g = None

    if not has_override(target):
        target.override_set_at = None

    session.commit()
    session.refresh(target)
    return target
