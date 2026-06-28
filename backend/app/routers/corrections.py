"""Derived-item edit route (FTY-051).

``PATCH /api/users/{user_id}/derived-items/{item_type}/{item_id}`` applies a
single deterministic user override to a derived food/exercise item, preserving the
estimator's original value and appending immutable correction rows.

The ``{user_id}`` path is explicit so object-level ownership is checked on every
edit. A cross-user or unknown target renders ``404`` — the API never confirms
another user's item exists nor mutates it (fail closed). Semantic rejections
(unknown field, out-of-range value, invalid quantity) render ``422`` with a
machine-readable error shape that never echoes the item's values.
"""

from __future__ import annotations

import uuid
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import CurrentUser
from app.enums import CandidateType
from app.models.derived import DerivedExerciseItem, DerivedFoodItem
from app.schemas.corrections import (
    DerivedExerciseItemDTO,
    DerivedFoodItemDTO,
    DerivedItemEditRequest,
)
from app.services import corrections as corrections_service
from app.services import item_read_model
from app.services.corrections import (
    DerivedItemForbidden,
    DerivedItemNotFound,
    InvalidCorrection,
)

router = APIRouter(prefix="/api/users", tags=["corrections"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="derived item not found")


@router.patch(
    "/{user_id}/derived-items/{item_type}/{item_id}",
    response_model=DerivedFoodItemDTO | DerivedExerciseItemDTO,
)
def edit_derived_item(
    user_id: uuid.UUID,
    item_type: CandidateType,
    item_id: uuid.UUID,
    payload: DerivedItemEditRequest,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> DerivedFoodItemDTO | DerivedExerciseItemDTO:
    """Edit one field of the caller's own derived item.

    A ``quantity`` edit on a food item is a **provenance-preserving** amount adjust
    (rescales calories/macros, keeps the source, leaves the item un-edited); a direct
    value edit is a **user override** (marks the item edited). Either way the original
    value is snapshotted and immutable correction row(s) are appended. The response
    carries the per-item ``source`` descriptor and ``is_edited`` flag. Cross-user or
    unknown targets fail closed as ``404``; invalid edits return ``422`` with a clear
    error shape.
    """

    try:
        result = corrections_service.edit_derived_item(
            session,
            user_id,
            current_user,
            item_type,
            item_id,
            payload.field,
            payload.value,
        )
    except (DerivedItemForbidden, DerivedItemNotFound) as exc:
        raise _NOT_FOUND from exc
    except InvalidCorrection as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": exc.code, "field": exc.field},
        ) from exc

    if item_type is CandidateType.FOOD:
        return item_read_model.serialize_food_item(session, cast("DerivedFoodItem", result.item))
    return item_read_model.serialize_exercise_item(
        session, cast("DerivedExerciseItem", result.item)
    )
