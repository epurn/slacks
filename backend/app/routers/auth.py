"""Local auth routes: register and login. Thin boundary over the auth service."""

from __future__ import annotations

import logging
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
from app.security.rate_limit import RateLimitDecision, RateLimiter, account_key, ip_key
from app.services import auth as auth_service
from app.services.auth import AuthError, IssuedToken
from app.settings import Settings

router = APIRouter(prefix="/api/auth", tags=["auth"])

logger = logging.getLogger(__name__)

_CONFLICT_STATUS = {
    "conflict": status.HTTP_409_CONFLICT,
    "invalid": status.HTTP_401_UNAUTHORIZED,
}


def _token_response(issued: IssuedToken) -> TokenResponse:
    return TokenResponse(access_token=issued.access_token, expires_in=issued.expires_in)


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _client_ip(request: Request, settings: Settings) -> str:
    """Return the effective client IP used as the per-IP rate-limit key.

    Defaults to ``request.client.host`` (the real TCP peer). Honours
    ``X-Forwarded-For`` only when ``settings.rate_limit_trusted_proxy`` is
    explicitly enabled, and then takes the **rightmost** entry.

    Why rightmost, not leftmost: proxies *append* to ``X-Forwarded-For``, so the
    leftmost entry is the client-supplied value. An attacker who sends
    ``X-Forwarded-For: <forged>`` has the trusted proxy append the real peer
    after it, leaving forged values to the left — reading the leftmost entry
    would let them mint a fresh per-IP key per request and defeat per-IP
    limiting (the very abuse this feature prevents). The rightmost entry is the
    hop the trusted proxy itself wrote, i.e. the address it observed the request
    coming from, so it cannot be spoofed.

    Assumption: exactly one trusted proxy sits directly in front of the app
    (the only safe topology for trusting XFF). If that proxy *overwrites* XFF
    with a single value, leftmost == rightmost and this is equivalent; with
    additional hops, the trusted layer must overwrite, or this must be extended
    to strip the known trusted hops from the right.
    """
    if settings.rate_limit_trusted_proxy:
        forwarded = request.headers.get("X-Forwarded-For", "")
        hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
        if hops:
            return hops[-1]
    return request.client.host if request.client else "unknown"


_FAIL_CLOSED_RETRY_AFTER = "5"


def _enforce_rate_limit(
    limiter: RateLimiter,
    key: str,
    limit: int,
    window_seconds: int,
    fail_open: bool,
) -> None:
    """Enforce one rate-limit key; raise 429 if throttled.

    When the limiter raises (e.g. Redis unavailable):
    - ``fail_open=True``: allow the request and emit a warn (dev/self-host default).
    - ``fail_open=False``: deny with 503 + Retry-After and emit a warn (prod default).
      The credential verify is never reached, so there is no hash/DB cost and no
      account-existence oracle even in the fail-closed path.
    """
    decision: RateLimitDecision
    try:
        decision = limiter.check(key, limit, window_seconds)
    except Exception:
        if fail_open:
            logger.warning("rate-limit check raised; allowing request (fail-open)")
            return
        logger.warning("rate-limit check raised; denying request (fail-closed)")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable. Please try again later.",
            headers={"Retry-After": _FAIL_CLOSED_RETRY_AFTER},
        ) from None
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(decision.retry_after)},
        )


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
def register(
    payload: RegisterRequest,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(_settings)],
) -> RegisterResponse:
    """Register a new local user and return the user plus a session token."""

    limiter: RateLimiter = request.app.state.rate_limiter
    ip = _client_ip(request, settings)
    _enforce_rate_limit(
        limiter,
        ip_key(ip, "register"),
        settings.rate_limit_register_ip_max,
        settings.rate_limit_register_ip_window,
        fail_open=settings.rate_limit_fail_open,
    )

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
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(_settings)],
) -> TokenResponse:
    """Verify credentials and return a bearer token."""

    limiter: RateLimiter = request.app.state.rate_limiter
    ip = _client_ip(request, settings)

    # Per-IP check first; short-circuits before the per-account check and before
    # the credential verify so a flood pays no hash/DB cost.
    _enforce_rate_limit(
        limiter,
        ip_key(ip, "login"),
        settings.rate_limit_login_ip_max,
        settings.rate_limit_login_ip_window,
        fail_open=settings.rate_limit_fail_open,
    )
    # Per-account check blunts credential-stuffing that rotates IPs against one
    # account. Same 429 short-circuit for both known and unknown emails — no
    # account-existence oracle is added.
    _enforce_rate_limit(
        limiter,
        account_key(payload.email),
        settings.rate_limit_login_account_max,
        settings.rate_limit_login_account_window,
        fail_open=settings.rate_limit_fail_open,
    )

    try:
        _, issued = auth_service.authenticate(
            session, payload.email, payload.password.get_secret_value(), settings
        )
    except AuthError as exc:
        raise HTTPException(status_code=_CONFLICT_STATUS[exc.kind], detail=str(exc)) from exc

    return _token_response(issued)
