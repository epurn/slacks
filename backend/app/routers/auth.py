"""Local auth routes: register and login. Thin boundary over the auth service."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserDTO,
)
from app.services import auth as auth_service
from app.services.auth import AuthError, IssuedToken
from app.settings import Settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

_CONFLICT_STATUS = {
    "conflict": status.HTTP_409_CONFLICT,
    "invalid": status.HTTP_401_UNAUTHORIZED,
}


def _token_response(issued: IssuedToken) -> TokenResponse:
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(_settings)],
) -> RegisterResponse:
    """Register a new local user and return the user plus a session token."""

    try:
        user, issued = auth_service.register_user(
            session, payload.email, payload.password.get_secret_value(), settings
        )
    except AuthError as exc:
        raise HTTPException(status_code=_CONFLICT_STATUS[exc.kind], detail=str(exc)) from exc

    return RegisterResponse(user=UserDTO.model_validate(user), token=_token_response(issued))


@router.post("/login", response_model=TokenResponse)
def login(
    payload: LoginRequest,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(_settings)],
) -> TokenResponse:
    """Verify credentials and return a bearer token."""

    try:
        _, issued = auth_service.authenticate(
            session, payload.email, payload.password.get_secret_value(), settings
        )
    except AuthError as exc:
        raise HTTPException(status_code=_CONFLICT_STATUS[exc.kind], detail=str(exc)) from exc

    return _token_response(issued)
