"""Auth boundary DTOs (FTY-020).

These shapes are a contract consumed by clients and later stories. Passwords are
carried as :class:`~pydantic.SecretStr` so they are never rendered in logs,
reprs, or error output, and password hashes are never part of any response model.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

#: Pragmatic email check (one ``@``, a dotted domain). Intentionally not a full
#: RFC 5322 validator: it avoids a third-party email-validation dependency while
#: still rejecting obviously malformed input at the boundary.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

#: Password input bounds. The lower bound is a minimal strength floor; the upper
#: bound caps work done by the (deliberately expensive) hash to avoid a
#: long-password denial-of-service.
PasswordStr = Annotated[SecretStr, Field(min_length=8, max_length=128)]


def _normalize_email(value: str) -> str:
    """Lower-case, trim, and validate an email identifier."""

    candidate = value.strip().lower()
    if not _EMAIL_RE.match(candidate):
        raise ValueError("invalid email address")
    return candidate


class RegisterRequest(BaseModel):
    """Request body for ``POST /api/auth/register``."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=320)
    password: PasswordStr

    _normalize = field_validator("email")(_normalize_email)


class LoginRequest(BaseModel):
    """Request body for ``POST /api/auth/login``."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(max_length=320)
    password: PasswordStr

    _normalize = field_validator("email")(_normalize_email)


class TokenResponse(BaseModel):
    """Bearer token returned by register/login. ``expires_in`` is seconds."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 (OAuth token type, not a secret)
    expires_in: int


class UserDTO(BaseModel):
    """Public view of a user record. Carries identity, never credentials."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime


class RegisterResponse(BaseModel):
    """Response for a successful registration: the new user plus a session token."""

    user: UserDTO
    token: TokenResponse
