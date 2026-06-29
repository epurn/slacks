"""Weight-entry service: create, list-by-range, delete (FTY-070).

This module owns two contracts:

1. **Units conversion.** :func:`to_canonical_kg` is the single, deterministic
   conversion path from a user's display units (lb or kg) to canonical
   kilograms. The NIST factor (1 lb = 0.45359237 kg) is defined once here so
   this path and any future consumers (the target calculator, the profile
   update) all agree. Weight values are sensitive personal data and must never
   appear in log output.

2. **Object-level authorization.** Every access path runs through
   :func:`_authorize`, which fails closed: a caller may only create, list, or
   delete *their own* weight entries. A mismatch raises
   :class:`WeightEntryForbidden`, which the router renders as ``404`` so the
   API never confirms another user's entries exist (no existence oracle).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.enums import UnitsPreference
from app.models.identity import User, UserProfile
from app.models.weight_entries import WeightEntry
from app.timeutils import current_day

#: Canonical NIST conversion factor: 1 international avoirdupois pound in kg.
_LB_TO_KG: float = 0.45359237

#: Upper bound of plausible body weight in canonical kg (mirrors profile validation).
_MAX_WEIGHT_KG: float = 1000.0

#: Earliest accepted effective_date — rejects absurd past typos while leaving any
#: realistic historical backfill untouched.
_DATE_FLOOR: date = date(1900, 1, 1)

#: How many days ahead of "today in the user's timezone" we accept — absorbs
#: clock/tz skew between the client and the server's resolved "today".
_DATE_SLACK_DAYS: int = 1


class WeightEntryForbidden(Exception):
    """Raised when a caller tries to access weight entries they do not own."""


class WeightEntryNotFound(Exception):
    """Raised when a weight entry does not exist for the owning user."""


class InvalidWeightValue(Exception):
    """Raised when the canonical kg weight is outside the plausible (0, 1000] range."""


class InvalidWeightDate(Exception):
    """Raised when effective_date is outside the accepted range.

    The accepted range is [1900-01-01, today-in-user-tz + 1 day slack].
    """


def lb_to_kg(weight_lb: float) -> float:
    """Convert pounds to canonical kilograms using the exact NIST factor.

    1 international avoirdupois pound = 0.45359237 kg (exact, by definition).
    This is a pure, deterministic function: the same lb value always produces
    the same kg value.
    """

    return weight_lb * _LB_TO_KG


def to_canonical_kg(weight: float, units_preference: str) -> float:
    """Convert ``weight`` from the user's display units to canonical kilograms.

    For ``metric`` users the value is already in kg and is returned unchanged.
    For ``imperial`` users the value is treated as pounds and converted via the
    exact NIST factor. This is the single conversion path shared by the
    weight-entry, profile, and exercise-burn contracts.
    """

    if units_preference == UnitsPreference.IMPERIAL:
        return lb_to_kg(weight)
    return weight


def create_entry(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    weight: float,
    effective_date: date,
) -> WeightEntry:
    """Create a weight entry for ``owner_id``, enforcing ownership.

    ``weight`` is in the user's ``units_preference`` and is converted to
    canonical kg before persistence. Raises :class:`InvalidWeightValue` if the
    canonical value is outside ``(0, 1000]`` kg.
    """

    _authorize(owner_id, current_user)
    today = current_day(session, owner_id)
    if effective_date < _DATE_FLOOR:
        raise InvalidWeightDate(
            f"effective_date must be on or after {_DATE_FLOOR}; got {effective_date}"
        )
    if effective_date > today + timedelta(days=_DATE_SLACK_DAYS):
        raise InvalidWeightDate(
            f"effective_date must be on or before today in the user's timezone"
            f" (+{_DATE_SLACK_DAYS} day slack); got {effective_date}"
        )
    units = _user_units_preference(session, owner_id)
    weight_kg = to_canonical_kg(weight, units)
    if weight_kg <= 0 or weight_kg > _MAX_WEIGHT_KG:
        raise InvalidWeightValue(
            f"weight must be in (0, {_MAX_WEIGHT_KG}] kg after conversion; got {weight_kg}"
        )
    entry = WeightEntry(user_id=owner_id, weight_kg=weight_kg, effective_date=effective_date)
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def list_entries(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[WeightEntry]:
    """Return ``owner_id``'s entries whose effective date falls in ``[from_date, to_date]``.

    Both bounds are optional; omitting one leaves that end of the range open.
    Results are ordered oldest-first (by effective date, then insertion id as a
    stable tiebreaker for multiple entries on the same date).
    """

    _authorize(owner_id, current_user)
    query = select(WeightEntry).where(WeightEntry.user_id == owner_id)
    if from_date is not None:
        query = query.where(WeightEntry.effective_date >= from_date)
    if to_date is not None:
        query = query.where(WeightEntry.effective_date <= to_date)
    query = query.order_by(WeightEntry.effective_date.asc(), WeightEntry.id.asc())
    return list(session.scalars(query))


def delete_entry(
    session: Session,
    owner_id: uuid.UUID,
    current_user: User,
    entry_id: uuid.UUID,
) -> None:
    """Delete one of ``owner_id``'s weight entries, enforcing ownership.

    The query is scoped to ``owner_id`` so a cross-user ``entry_id`` is
    indistinguishable from a missing one (no existence oracle); both raise
    :class:`WeightEntryNotFound`, which the router renders as ``404``.
    """

    _authorize(owner_id, current_user)
    entry = session.scalars(
        select(WeightEntry).where(WeightEntry.id == entry_id, WeightEntry.user_id == owner_id)
    ).one_or_none()
    if entry is None:
        raise WeightEntryNotFound("weight entry not found")
    session.delete(entry)
    session.commit()


def _authorize(owner_id: uuid.UUID, current_user: User) -> None:
    """Fail closed unless ``current_user`` owns ``owner_id``'s weight entries."""

    if owner_id != current_user.id:
        raise WeightEntryForbidden("cross-user weight-entry access denied")


def _user_units_preference(session: Session, owner_id: uuid.UUID) -> str:
    """Resolve the owner's units preference, falling back to metric.

    The profile is created at registration with a validated ``units_preference``,
    so this normally loads; the metric fallback keeps creates robust if a profile
    is somehow absent.
    """

    pref = session.scalars(
        select(UserProfile.units_preference).where(UserProfile.user_id == owner_id)
    ).one_or_none()
    return pref or UnitsPreference.METRIC
