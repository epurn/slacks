"""Shared FastAPI dependencies for authenticated routes.

:func:`get_current_user` is the single trust boundary for bearer tokens: it
parses and verifies the token, then loads the owning user. Any failure raises
``401`` so protected routes fail closed.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.models.identity import User
from app.security.tokens import InvalidToken, parse_token
from app.settings import Settings

_UNAUTHORIZED = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="missing or invalid credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Resolve the authenticated user from the ``Authorization: Bearer`` header.

    Raises ``401`` if the header is missing/malformed, the token fails
    verification, or the referenced user no longer exists.
    """

    if authorization is None or not authorization.lower().startswith("bearer "):
        raise _UNAUTHORIZED
    token = authorization[len("bearer ") :].strip()

    settings: Settings = request.app.state.settings
    try:
        user_id = parse_token(token, settings.auth_secret.get_secret_value())
    except InvalidToken as exc:
        raise _UNAUTHORIZED from exc

    user = session.get(User, user_id)
    if user is None:
        raise _UNAUTHORIZED
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
