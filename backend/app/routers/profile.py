"""Profile read/write routes with object-level authorization (FTY-020).

The ``{user_id}`` path is explicit so ownership is checked on every access. A
caller may only read/write their own profile; the service raises on a mismatch
and this router renders that as ``404`` so other users' profiles are not even
confirmed to exist.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import CurrentUser
from app.schemas.profile import ProfileDTO, ProfileUpdateRequest
from app.services import profile as profile_service
from app.services.profile import ProfileForbidden

router = APIRouter(prefix="/api/users", tags=["profile"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="profile not found")


@router.get("/{user_id}/profile", response_model=ProfileDTO)
def read_profile(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> ProfileDTO:
    """Return the caller's own profile, or ``404`` for anyone else's."""

    try:
        profile = profile_service.get_profile(session, user_id, current_user)
    except ProfileForbidden as exc:
        raise _NOT_FOUND from exc
    return ProfileDTO.model_validate(profile)


@router.put("/{user_id}/profile", response_model=ProfileDTO)
def write_profile(
    user_id: uuid.UUID,
    payload: ProfileUpdateRequest,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> ProfileDTO:
    """Apply a partial update to the caller's own profile, or ``404`` otherwise."""

    try:
        profile = profile_service.update_profile(session, user_id, current_user, payload)
    except ProfileForbidden as exc:
        raise _NOT_FOUND from exc
    return ProfileDTO.model_validate(profile)
