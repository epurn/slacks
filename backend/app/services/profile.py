"""Profile read/write service with object-level authorization (FTY-020).

Every access path goes through :func:`_authorize`, which fails closed: a caller
may only touch *their own* profile. A mismatch raises :class:`ProfileForbidden`,
which the router renders as ``404 Not Found`` so the API does not even confirm
that another user's profile exists (no existence oracle).

A write also keeps the user's daily target honest (FTY-467): editing a body metric
the target calculator consumes recomputes the active goal's derived target for the
current day, so the numbers read back after the write are the fresh derivation
rather than the goal-creation-day snapshot.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import User, UserProfile
from app.schemas.profile import ProfileUpdateRequest
from app.services.targets import recompute_active_target

#: Profile fields the target calculator actually consumes: ``height_m``, age (from
#: ``birth_year``), and the metabolic formula's sex-dependent constant. Changing one
#: moves the derived daily target, so it triggers a recompute.
#:
#: ``weight_kg`` is deliberately **not** one of them — the trajectory's weights come
#: from the goal's fixed ``start_weight_kg`` snapshot, not the profile — and
#: ``units_preference`` / ``timezone`` are display/locale settings, not body metrics.
#: Recomputing on those would be a pointless write producing identical numbers.
CALCULATOR_FIELDS = frozenset({"height_m", "birth_year", "metabolic_formula"})


class ProfileForbidden(Exception):
    """Raised when a caller tries to access a profile they do not own."""


def get_profile(session: Session, owner_id: uuid.UUID, current_user: User) -> UserProfile:
    """Return ``owner_id``'s profile, enforcing that the caller owns it."""

    _authorize(owner_id, current_user)
    return _load_or_create(session, owner_id)


def update_profile(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    update: ProfileUpdateRequest,
) -> UserProfile:
    """Apply a partial profile update for ``owner_id``, enforcing ownership.

    Only fields explicitly provided in ``update`` are written, so clients can
    capture body metrics incrementally without clobbering untouched values.

    When the update **changes** a calculator input (:data:`CALCULATOR_FIELDS`), the
    active goal's derived daily target for the current day is recomputed after the
    profile write commits (FTY-467), so a corrected height or a switched formula
    variant actually moves the target the app reads back. The recompute preserves an
    in-force user override and degrades to a silent no-op when it cannot run (no
    active goal covering today, or an edit that leaves the profile un-derivable), so
    the profile write itself never fails because of it — see
    :func:`~app.services.targets.recompute_active_target`.
    """

    _authorize(owner_id, current_user)
    profile = _load_or_create(session, owner_id)

    changes = update.model_dump(exclude_unset=True)
    recompute = _changes_a_calculator_input(profile, changes)
    for field, value in changes.items():
        setattr(profile, field, value)

    session.add(profile)
    session.commit()
    session.refresh(profile)

    if recompute:
        recompute_active_target(session, owner_id, current_user)
    return profile


def _changes_a_calculator_input(profile: UserProfile, changes: dict[str, Any]) -> bool:
    """True when ``changes`` moves a calculator input off its stored value.

    Only a real *change* triggers a recompute: a settings form that re-submits the
    height it just read would otherwise cost a write that produces identical numbers.
    Read before the update is applied, so it compares against the stored values.
    """

    return any(
        field in changes and changes[field] != getattr(profile, field)
        for field in CALCULATOR_FIELDS
    )


def _authorize(owner_id: uuid.UUID, current_user: User) -> None:
    """Fail closed unless ``current_user`` owns ``owner_id``'s profile."""

    if owner_id != current_user.id:
        raise ProfileForbidden("cross-user profile access denied")


def _load_or_create(session: Session, owner_id: uuid.UUID) -> UserProfile:
    """Load the user's profile, creating an empty one if it does not exist yet.

    Registration always creates a profile, so this normally loads; the
    create-on-read fallback keeps the endpoint robust if a profile is ever
    missing without leaking another user's data (ownership is already checked).
    """

    profile = session.scalars(
        select(UserProfile).where(UserProfile.user_id == owner_id)
    ).one_or_none()
    if profile is None:
        profile = UserProfile(user_id=owner_id)
        session.add(profile)
        session.commit()
        session.refresh(profile)
    return profile
