"""Item re-match routes — list alternatives + re-resolve (FTY-093).

Two thin HTTP operations over a food item's "Change match" lever:

- ``POST /api/users/{user_id}/derived-items/food/{item_id}/source-candidates``
  lists bounded alternative source matches (with an optional sanitized query
  override).
- ``POST /api/users/{user_id}/derived-items/food/{item_id}/re-resolve`` re-aims the
  item to a chosen candidate **reference**, recomputing from that source at the
  item's current portion and rewriting its provenance honestly to the new source.

Both are **thin pass-throughs**: they validate the request, check object-level
ownership, and delegate to the estimator's :class:`~app.estimator.re_match.ReMatchCapability`
(which owns all resolution, recompute, and persistence). The ``{user_id}`` path is
explicit so ownership is checked on every call; a cross-user or unknown item renders
``404`` — the API never confirms another user's item exists nor mutates it (fail
closed), matching the FTY-051 corrections posture. Both routes also fail closed
(``404``) when the item's parent log event is **voided** (FTY-321): they return or
mutate the target row directly, bypassing the read-time exclusion join, so a
backend-core boundary precheck refuses voided targets before the capability runs —
the estimator itself stays void-agnostic. A chosen reference the server
cannot re-derive, or a re-match the new source cannot cost, renders ``422`` with a
machine-readable shape that never echoes the item's values. A transient or unusable
candidate-source failure during listing renders a retryable ``503`` rather than a
misleading empty candidate list.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import CurrentUser
from app.enums import CandidateType, SourceType
from app.estimator.re_match import (
    AlternativesUnavailable,
    ItemForbidden,
    ItemNotFound,
    ReMatchNeedsClarification,
    SourceCandidate,
    SourceNotResolvable,
    build_re_match_capability,
)
from app.schemas.corrections import DerivedFoodItemDTO
from app.schemas.re_match import (
    AlternativesResponse,
    ListAlternativesRequest,
    ReResolveRequest,
    SourceCandidateDTO,
)
from app.services import item_read_model
from app.services.corrections import DerivedItemNotFound, ensure_parent_event_not_voided

router = APIRouter(prefix="/api/users", tags=["re-match"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="derived item not found")


def _refuse_voided_parent(session: Session, item_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    """FTY-321 boundary precheck: ``404`` when the item's parent event is voided.

    Runs before the estimator capability is invoked, so a voided target is
    refused at the backend-core boundary and the capability (which is
    void-agnostic) never loads it. A missing or cross-user item passes through —
    the capability's own owner-scoped loader reports those as ``404``.
    """

    try:
        ensure_parent_event_not_voided(session, CandidateType.FOOD, item_id, owner_id)
    except DerivedItemNotFound as exc:
        raise _NOT_FOUND from exc


@router.post(
    "/{user_id}/derived-items/food/{item_id}/source-candidates",
    response_model=AlternativesResponse,
)
def list_source_candidates(
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ListAlternativesRequest,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> AlternativesResponse:
    """List alternative source candidates for the caller's own food item.

    Runs the existing resolution providers in list-candidates mode over the item's
    identity (or the sanitized ``query`` override) and returns a bounded list of
    energy-bearing matches. Cross-user or unknown items — and items whose parent
    log event is voided (FTY-321) — fail closed as ``404``; a transient or unusable
    candidate-source failure returns ``503`` (retryable) rather than a misleading
    empty list.
    """

    _refuse_voided_parent(session, item_id, user_id)
    capability = build_re_match_capability(session)
    try:
        candidates = capability.list_alternatives(
            owner_id=user_id,
            current_user=current_user,
            item_id=item_id,
            query_override=payload.query,
        )
    except (ItemForbidden, ItemNotFound) as exc:
        raise _NOT_FOUND from exc
    except AlternativesUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "alternatives_unavailable"},
        ) from exc

    return AlternativesResponse(candidates=[_candidate_dto(candidate) for candidate in candidates])


@router.post(
    "/{user_id}/derived-items/food/{item_id}/re-resolve",
    response_model=DerivedFoodItemDTO,
)
def re_resolve_item(
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ReResolveRequest,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> DerivedFoodItemDTO:
    """Re-resolve the caller's own food item to a chosen candidate reference.

    Recomputes calories/macros from the chosen source at the item's current portion,
    rewrites its provenance to the new source, and re-snapshots the estimated
    originals — the item is **not** marked edited. The response carries the new
    per-item ``source`` descriptor (FTY-092). Cross-user or unknown items — and items
    whose parent log event is voided (FTY-321) — fail closed as ``404``; a reference
    the server cannot re-derive, or a re-match the new source cannot cost, returns
    ``422`` with a clear error shape.
    """

    _refuse_voided_parent(session, item_id, user_id)
    capability = build_re_match_capability(session)
    try:
        item = capability.re_resolve(
            owner_id=user_id,
            current_user=current_user,
            item_id=item_id,
            source_ref=payload.source_ref,
        )
    except (ItemForbidden, ItemNotFound) as exc:
        raise _NOT_FOUND from exc
    except SourceNotResolvable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "source_not_resolvable"},
        ) from exc
    except ReMatchNeedsClarification as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "needs_clarification", "question": exc.question},
        ) from exc

    return item_read_model.serialize_food_item(session, item)


def _candidate_dto(candidate: SourceCandidate) -> SourceCandidateDTO:
    """Map an estimator :class:`SourceCandidate` to its boundary DTO (preview only)."""

    return SourceCandidateDTO(
        source_type=SourceType(candidate.source_type),
        source_ref=candidate.source_ref,
        name=candidate.name,
        basis=candidate.basis,  # type: ignore[arg-type]  # provider emits a canonical basis literal
        calories=candidate.facts.calories,
        protein_g=candidate.facts.protein_g,
        carbs_g=candidate.facts.carbs_g,
        fat_g=candidate.facts.fat_g,
    )
