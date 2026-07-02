"""Canonical identity and profile ORM models (FTY-020).

Three tables form the persistence contract:

- ``users`` — the canonical account/identity row. Deliberately minimal: it holds
  no credentials, so authentication material can never leak through a user
  record.
- ``auth_identities`` — authentication credentials kept *separate* from
  ``users`` per the security baseline. One user may have several identities
  (local email+password now; hosted providers later). Password hashes live here
  and are never logged.
- ``user_profiles`` — the user's body/preference data. Body metrics are stored
  in canonical units (height in metres, weight in kilograms); the user's display
  preference is a separate field, not a storage unit.

Every user-owned row carries a ``user_id`` foreign key with ``ON DELETE
CASCADE`` so account deletion removes the dependent identity and profile rows
(retention: profile retained until edited or account deletion).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Float, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, UtcDateTime
from app.enums import AuthProvider, MetabolicFormula, UnitsPreference


def _utcnow() -> datetime:
    """Timezone-aware UTC now, used for portable Python-side timestamp defaults."""

    return datetime.now(UTC)


class User(Base):
    """A canonical user account. Holds identity, never credentials."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    identities: Mapped[list[AuthIdentity]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    profile: Mapped[UserProfile | None] = relationship(
        back_populates="user", cascade="all, delete-orphan", uselist=False
    )


class AuthIdentity(Base):
    """An authentication credential for a user, separate from the user record.

    ``(provider, identifier)`` is unique: a given email can back at most one
    local identity. ``password_hash`` holds a self-describing strong hash (see
    :mod:`app.security.passwords`) and is nullable so non-password providers can
    be added later without a schema change.
    """

    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint("provider", "identifier", name="uq_auth_provider_identifier"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default=AuthProvider.LOCAL)
    # The login identifier for the provider (email for the local path). Stored
    # lower-cased by the auth service so lookups are case-insensitive.
    identifier: Mapped[str] = mapped_column(String(320), nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    user: Mapped[User] = relationship(back_populates="identities")


class UserProfile(Base):
    """A user's body metrics and display preferences, owned by exactly one user.

    Canonical units only: ``height_m`` in metres, ``weight_kg`` in kilograms.
    ``units_preference`` is the display choice and never changes what is stored.
    All metric fields are nullable so a profile can exist before capture (FTY-021)
    completes it.
    """

    __tablename__ = "user_profiles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    height_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    birth_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Pre-capture placeholder only: a fresh profile carries the unspecified
    # family default so the column is never null, and FTY-021 capture forces the
    # user to pick a +5/-161 variant before any target is computed. The default
    # names the formula but carries no constant, so it implies nothing until
    # capture overwrites it.
    metabolic_formula: Mapped[str] = mapped_column(
        String(32), nullable=False, default=MetabolicFormula.MIFFLIN_ST_JEOR
    )
    units_preference: Mapped[str] = mapped_column(
        String(16), nullable=False, default=UnitsPreference.METRIC
    )
    # IANA timezone name (e.g. "America/New_York"); validated at the DTO boundary.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        UtcDateTime, nullable=False, default=_utcnow, onupdate=_utcnow
    )

    user: Mapped[User] = relationship(back_populates="profile")
