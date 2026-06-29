"""Goal + target-reveal route with object-level authorization (FTY-106).

A single authenticated, owner-scoped write that turns onboarding's inputs — a
**direction** and an evidence-based **pace preset** — into a persisted active goal
and the **computed daily calorie target returned with its provenance**:

- ``POST /api/users/{user_id}/goal`` — create/replace the active goal and reveal
  its target (``goal`` + ``target`` + ``provenance`` + ``clamp``).

The ``{user_id}`` path is explicit so object-level ownership is checked on every
access; a cross-user request and a missing/unowned goal are indistinguishable and
both fail closed as ``404`` (no existence oracle). An incomplete profile is refused
``409`` (complete the profile first), and a pace not offered for the direction is
refused ``422``. Weight, RMR, TDEE, and the target are sensitive derived body data
and are never logged.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import CurrentUser
from app.schemas.goals import GoalTargetRequest, GoalTargetResponse
from app.services import goals as goals_service
from app.services.goals import InvalidPace
from app.services.targets import GoalForbidden, IncompleteProfileError

router = APIRouter(prefix="/api/users", tags=["goals"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="goal not found")


@router.post(
    "/{user_id}/goal",
    response_model=GoalTargetResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_goal(
    user_id: uuid.UUID,
    payload: GoalTargetRequest,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> GoalTargetResponse:
    """Create/replace the caller's active goal and reveal its computed target.

    The new goal deactivates any prior active goal (one active goal per user) and
    today's ``daily_targets`` row is persisted as a side effect, so the reveal — and
    a subsequent ``GET daily-summary`` for today — shows a real number. Fails closed
    ``404`` on cross-user access; ``409`` when the profile is incomplete; ``422`` when
    the pace is not offered for the direction (or the request body is malformed).
    """

    try:
        goal, target = goals_service.create_goal_with_target(
            session, user_id, current_user, payload
        )
    except GoalForbidden as exc:
        raise _NOT_FOUND from exc
    except InvalidPace as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except IncompleteProfileError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="profile must be completed before a target can be computed",
        ) from exc
    return goals_service.build_goal_target_response(goal, target, payload.direction)
