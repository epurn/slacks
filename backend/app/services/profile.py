"""Profile read/write service with object-level authorization (FTY-020).

Every access path goes through :func:`_authorize`, which fails closed: a caller
may only touch *their own* profile. A mismatch raises :class:`ProfileForbidden`,
which the router renders as ``404 Not Found`` so the API does not even confirm
that another user's profile exists (no existence oracle).
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.identity import User, UserProfile
from app.schemas.profile import ProfileUpdateRequest


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
    """

    _authorize(owner_id, current_user)
    profile = _load_or_create(session, owner_id)

    for field, value in update.model_dump(exclude_unset=True).items():
        setattr(profile, field, value)

    session.add(profile)
    session.commit()
    session.refresh(profile)
    return profile


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
