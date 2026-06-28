"""Authentication service for the local email+password path.

Holds the registration and login behaviour so the routers stay thin HTTP
boundaries. Errors are raised as :class:`AuthError` with a ``kind`` the router
maps to a status code, so the HTTP vocabulary lives at the edge, not here.

Security posture:

- Passwords are hashed with :mod:`app.security.passwords`; the plaintext never
  leaves this call and the hash lives only on the auth identity row.
- Login does not reveal whether the email exists: an unknown email still pays
  the cost of a hash verification (against a dummy hash) and returns the same
  generic "invalid credentials" error as a wrong password.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.enums import AuthProvider
from app.models.identity import AuthIdentity, User, UserProfile
from app.security.passwords import hash_password, verify_password
from app.security.tokens import mint_token
from app.settings import Settings

#: A precomputed hash of a random throwaway password. Verifying against it gives
#: the "unknown email" path the same timing as a real password check, blunting
#: user-enumeration via response timing.
_DUMMY_HASH = hash_password(uuid.uuid4().hex)


class AuthError(Exception):
    """An authentication failure the router maps to an HTTP status.

    ``kind`` is ``"conflict"`` (email already registered) or ``"invalid"``
    (registration/login credentials rejected).
    """

    def __init__(self, kind: Literal["conflict", "invalid"], message: str) -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class IssuedToken:
    """A minted bearer token and its lifetime in seconds."""

    access_token: str
    expires_in: int


def register_user(
    session: Session, email: str, password: str, settings: Settings
) -> tuple[User, IssuedToken]:
    """Register a new local user, creating the user, auth identity, and profile.

    Raises :class:`AuthError` (``conflict``) if the email is already registered.
    """

    existing = _find_local_identity(session, email)
    if existing is not None:
        raise AuthError("conflict", "email already registered")

    user = User()
    identity = AuthIdentity(
        user=user,
        provider=AuthProvider.LOCAL,
        identifier=email,
        password_hash=hash_password(password),
    )
    profile = UserProfile(user=user)
    session.add_all([user, identity, profile])
    try:
        session.commit()
    except IntegrityError:
        # Two concurrent registrations of the same email both passed the
        # existence check; the loser hits uq_auth_provider_identifier. Mirror
        # the pattern in log_events.py: rollback and surface the same conflict
        # the sequential duplicate path already raises so the router maps it to
        # 409 without leaking internal detail.
        session.rollback()
        raise AuthError("conflict", "email already registered") from None
    session.refresh(user)

    return user, _issue_token(user.id, settings)


def authenticate(
    session: Session, email: str, password: str, settings: Settings
) -> tuple[User, IssuedToken]:
    """Verify credentials and issue a token, or raise :class:`AuthError`.

    The same generic ``invalid`` error is raised for an unknown email and a wrong
    password so callers cannot distinguish the two.
    """

    identity = _find_local_identity(session, email)
    if identity is None or identity.password_hash is None:
        # Equalize timing with the valid path before failing closed.
        verify_password(password, _DUMMY_HASH)
        raise AuthError("invalid", "invalid email or password")

    if not verify_password(password, identity.password_hash):
        raise AuthError("invalid", "invalid email or password")

    return identity.user, _issue_token(identity.user_id, settings)


def _find_local_identity(session: Session, email: str) -> AuthIdentity | None:
    """Look up the local auth identity for ``email`` (already normalized)."""

    stmt = select(AuthIdentity).where(
        AuthIdentity.provider == AuthProvider.LOCAL,
        AuthIdentity.identifier == email,
    )
    return session.scalars(stmt).one_or_none()


def _issue_token(user_id: uuid.UUID, settings: Settings) -> IssuedToken:
    """Mint a bearer token for ``user_id`` using the configured secret/TTL."""

    ttl = settings.auth_token_ttl_seconds
    token = mint_token(
        user_id,
        settings.auth_secret.get_secret_value(),
        ttl,
        now=datetime.now(UTC),
    )
    return IssuedToken(access_token=token, expires_in=ttl)
