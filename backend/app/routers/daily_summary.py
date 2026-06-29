"""Daily-summary route: read-only computed daily totals for a user (FTY-071).

``GET /api/users/{user_id}/daily-summary`` returns the authenticated user's own
separated calorie/macro totals for a requested day, computed in their profile
timezone. The ``{user_id}`` path is explicit so object-level ownership is checked
on every access; a cross-user request is indistinguishable from a missing account
and fails closed as ``404`` (no existence oracle, mirroring ``log-events.md``).

Sensitive nutrition data (totals, macros, target, burn) is never logged.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import CurrentUser
from app.schemas.daily_summary import DailySummaryDTO
from app.services import daily_summary as daily_summary_service
from app.services.daily_summary import (
    MAX_RANGE_DAYS,
    DailySummaryForbidden,
    DailySummaryInvalidRange,
    DailySummaryRangeTooLarge,
)

router = APIRouter(prefix="/api/users", tags=["daily-summary"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")


@router.get("/{user_id}/daily-summary", response_model=DailySummaryDTO)
def get_daily_summary(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    day: Annotated[
        date | None,
        Query(
            description=(
                "Calendar day (YYYY-MM-DD) in the user's profile timezone; "
                "defaults to today. A malformed value returns 422."
            )
        ),
    ] = None,
) -> DailySummaryDTO:
    """Return the authenticated user's daily summary for ``day``.

    Separated components: intake (calories + macros from finalized food items),
    target (calorie target from FTY-022, or ``null`` when none exists), and
    exercise (active-calorie burn from finalized exercise items). Burn is not
    pre-netted; the client computes net (intake − burn).

    Fails closed (``404``) on cross-user access; ``422`` for a malformed ``day``
    parameter; ``401`` for a missing or invalid bearer token.
    """

    try:
        return daily_summary_service.get_daily_summary(session, user_id, current_user, day)
    except DailySummaryForbidden as exc:
        raise _NOT_FOUND from exc


@router.get("/{user_id}/daily-summary/range", response_model=list[DailySummaryDTO])
def get_daily_summary_range(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    from_date: Annotated[
        date,
        Query(
            alias="from",
            description=("Inclusive start day (YYYY-MM-DD) in the user's profile timezone."),
        ),
    ],
    to_date: Annotated[
        date,
        Query(
            alias="to",
            description=(
                "Inclusive end day (YYYY-MM-DD) in the user's profile timezone; "
                f"the span may not exceed {MAX_RANGE_DAYS} days."
            ),
        ),
    ],
) -> list[DailySummaryDTO]:
    """Return the caller's per-day summaries for every day in ``[from, to]``.

    The range read-model behind the Trends adherence series: one request yields
    the whole window — every calendar day present, with zeroed intake/burn and a
    ``null`` target for days that have no finalized data — so the client never
    fans out one request per day. Ordered oldest-first.

    ``from`` must be on or before ``to`` and the span may not exceed
    ``MAX_RANGE_DAYS`` days (``422`` otherwise). Fails closed (``404``) on
    cross-user access; ``422`` for a malformed date; ``401`` for a missing or
    invalid bearer token.
    """

    try:
        return daily_summary_service.get_daily_summaries(
            session, user_id, current_user, from_date, to_date
        )
    except DailySummaryForbidden as exc:
        raise _NOT_FOUND from exc
    except (DailySummaryInvalidRange, DailySummaryRangeTooLarge) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
