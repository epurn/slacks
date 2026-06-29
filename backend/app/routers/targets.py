"""Target routes: read, manually override, and reset a user's daily targets (FTY-095).

Owner-scoped, fail-closed surface over the active goal's target for a day:

- ``GET    /api/users/{user_id}/target`` — the derived-vs-overridden read-model.
- ``PUT    /api/users/{user_id}/target/override`` — set a calorie and/or macro override.
- ``POST   /api/users/{user_id}/target/override/reset`` — clear override(s) back to derived.

The ``{user_id}`` path is explicit so object-level ownership is checked on every
access; a cross-user request and a user with no active goal / no stored target for
the day are indistinguishable and both fail closed as ``404`` (no existence
oracle). An out-of-band manual override is refused ``422`` — the user's explicit
value is rejected, never silently clamped. When an override write has to materialise
the day's row but the profile is incomplete, it fails ``409`` (complete the profile
first), the same mapping goal creation uses. Target numbers are sensitive derived
body data and are never logged.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import CurrentUser
from app.schemas.targets import (
    TargetOverrideRequest,
    TargetReadModel,
    TargetResetRequest,
)
from app.services import targets as target_service
from app.services.targets import (
    GoalForbidden,
    IncompleteProfileError,
    OverrideOutOfBand,
    TargetNotFound,
)

router = APIRouter(prefix="/api/users", tags=["targets"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="target not found")

_INCOMPLETE_PROFILE = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="profile must be completed before a target can be computed",
)

_DAY_QUERY = Query(
    description=(
        "Calendar day (YYYY-MM-DD) the target applies to; defaults to today. "
        "A malformed value returns 422."
    )
)


@router.get("/{user_id}/target", response_model=TargetReadModel)
def get_target(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    day: Annotated[date | None, _DAY_QUERY] = None,
) -> TargetReadModel:
    """Return the caller's active-goal target for ``day`` with provenance.

    Each target (calorie + macros) carries its effective value, derived value, and
    ``derived | user`` source. ``day`` defaults to today in the user's profile
    timezone. Fails closed ``404`` on cross-user access or when no active target
    exists for the day.
    """

    try:
        target = target_service.get_active_target(session, user_id, current_user, for_date=day)
    except (GoalForbidden, TargetNotFound) as exc:
        raise _NOT_FOUND from exc
    return target_service.build_target_read_model(target)


@router.put("/{user_id}/target/override", response_model=TargetReadModel)
def set_override(
    user_id: uuid.UUID,
    payload: TargetOverrideRequest,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    day: Annotated[date | None, _DAY_QUERY] = None,
) -> TargetReadModel:
    """Set a manual calorie and/or macro override on the caller's target for ``day``.

    Calorie and macro overrides can be set independently. An out-of-band value is
    refused ``422`` with nothing persisted; cross-user access or no active target
    fails closed ``404``. When materialising the day's row needs the calculator but
    the profile is incomplete, returns ``409`` (complete the profile first), matching
    goal creation. ``day`` defaults to today in the user's profile timezone.
    """

    try:
        target = target_service.set_target_override(
            session, user_id, current_user, payload, for_date=day
        )
    except (GoalForbidden, TargetNotFound) as exc:
        raise _NOT_FOUND from exc
    except IncompleteProfileError as exc:
        raise _INCOMPLETE_PROFILE from exc
    except OverrideOutOfBand as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return target_service.build_target_read_model(target)


@router.post("/{user_id}/target/override/reset", response_model=TargetReadModel)
def reset_override(
    user_id: uuid.UUID,
    payload: TargetResetRequest,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    day: Annotated[date | None, _DAY_QUERY] = None,
) -> TargetReadModel:
    """Reset the caller's override(s) for ``day`` back to the derived value.

    ``targets`` names which overrides to clear; omitting it clears all in-force
    overrides. Idempotent. Cross-user access or no active target fails closed
    ``404``. When materialising the day's row needs the calculator but the profile is
    incomplete, returns ``409`` (complete the profile first), matching goal creation.
    ``day`` defaults to today in the user's profile timezone.
    """

    try:
        target = target_service.reset_target_override(
            session, user_id, current_user, payload.targets, for_date=day
        )
    except (GoalForbidden, TargetNotFound) as exc:
        raise _NOT_FOUND from exc
    except IncompleteProfileError as exc:
        raise _INCOMPLETE_PROFILE from exc
    return target_service.build_target_read_model(target)
