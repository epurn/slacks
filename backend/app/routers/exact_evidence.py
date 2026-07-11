"""Exact-evidence apply route — the ``Make it exact`` apply half (FTY-307).

One thin HTTP operation over an existing food item:

- ``POST /api/users/{user_id}/derived-items/food/{item_id}/exact-upgrade/apply``
  applies a previously-generated, server-signed **proposal** (barcode FTY-308 /
  label FTY-309) to the item, in place: it verifies the opaque ``proposal_ref``
  belongs to this user + item, preserves the current amount (or applies an optional
  adjustment), rewrites the item's evidence provenance to the proposal's source,
  re-snapshots ``*_estimated``, and appends one ``re_match`` correction row.

It is a **thin pass-through**: it validates the request, checks object-level
ownership, refuses an item whose parent log event is **voided** (FTY-321), and
delegates to the estimator's
:class:`~app.estimator.exact_evidence.ExactEvidenceApplyCapability` (which owns
verification, recompute, and persistence). The ``{user_id}`` path is explicit so
ownership is checked on every call; a cross-user or unknown item — or a voided
parent — renders ``404`` with no existence disclosure and no mutation (fail
closed), matching the corrections / re-match posture. A tampered, expired,
wrong-user, or wrong-item proposal reference renders ``422 proposal_not_resolvable``;
an uncostable current/adjusted amount renders ``422 amount_required``. Every error
shape carries a stable code only — never nutrition values, a source ref, or the
proposal payload.

That last invariant also covers **request-schema** rejections. The signed
``proposal_ref`` is untrusted, potentially sensitive input, so a request that trips
Pydantic request validation on this endpoint (an oversized ``proposal_ref``, a
client-injected nutrition fact caught by ``extra="forbid"``, a malformed ``amount``)
must NOT fall through to FastAPI's default ``RequestValidationError`` response —
that body echoes the rejected ``input`` verbatim, reflecting the submitted
``proposal_ref`` or injected facts back to the caller.
:func:`sanitized_exact_evidence_validation_handler` replaces it with a content-free
``422 {"error": "invalid_request"}`` for this route (and the FTY-308 barcode-propose
route) only; every other endpoint keeps FastAPI's default validation body.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import CurrentUser
from app.enums import CandidateType
from app.estimator.barcode_proposal import BarcodeProposalGenerator
from app.estimator.exact_evidence import (
    AmountNotCostable,
    ProposalNotResolvable,
    build_exact_evidence_apply_capability,
)
from app.estimator.off import OffResponseError, OffTransientError
from app.estimator.re_match import ItemForbidden, ItemNotFound
from app.schemas.corrections import DerivedFoodItemDTO
from app.schemas.exact_evidence import (
    BarcodeProposalRequest,
    ExactEvidenceApplyRequest,
    ExactEvidenceProposalDTO,
)
from app.services import barcode_proposal as barcode_proposal_service
from app.services import item_read_model
from app.services.corrections import DerivedItemNotFound, ensure_parent_event_not_voided
from app.services.exact_evidence import NotUpgradeable
from app.settings import Settings

router = APIRouter(prefix="/api/users", tags=["exact-evidence"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="derived item not found")

#: Path suffixes whose request bodies carry untrusted, potentially sensitive input
#: (a signed ``proposal_ref``, a barcode, or client-injected nutrition facts caught by
#: ``extra="forbid"``). A validation failure on either must return a content-free code
#: rather than echo the rejected value. Matching the suffix uniquely selects these two
#: POST endpoints without coupling the sanitizer to the full parameterised paths.
_SANITIZED_PATH_SUFFIXES = ("/exact-upgrade/apply", "/exact-upgrade/barcode")


def _is_sanitized_request(request: Request) -> bool:
    """True when ``request`` targets an exact-evidence endpoint with sanitized errors."""

    return request.method == "POST" and request.url.path.endswith(_SANITIZED_PATH_SUFFIXES)


async def sanitized_exact_evidence_validation_handler(
    request: Request, exc: RequestValidationError
) -> Response:
    """Content-free ``422`` for exact-evidence request-validation failures; default elsewhere.

    Registered app-wide for :class:`RequestValidationError` (see
    ``app.main.create_app``), but only overrides the response for the exact-evidence
    apply and barcode-propose routes. FastAPI's default validation body echoes the
    rejected ``input`` — for these endpoints that would reflect the submitted signed
    ``proposal_ref`` / barcode or a client-injected nutrition fact (``extra="forbid"``)
    straight back to the caller, violating the stable-code-only error contract. For
    those routes we return ``{"detail": {"error": "invalid_request"}}`` — a stable code
    carrying no submitted value. Every other endpoint falls through to FastAPI's default
    handler so their validation-error contracts are unchanged.
    """

    if _is_sanitized_request(request):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={"detail": {"error": "invalid_request"}},
        )
    return await request_validation_exception_handler(request, exc)


def get_barcode_proposal_generator(
    session: Annotated[Session, Depends(get_session)],
) -> BarcodeProposalGenerator:
    """Build the per-request barcode proposal generator (FTY-308).

    A FastAPI dependency so tests can override it with a network-free generator; the
    default wires the real cache-first OFF resolver and the identity fallback over the
    configured LLM/search/fetch clients. Construction opens no socket.
    """

    return barcode_proposal_service.build_barcode_proposal_generator(session)


def _refuse_voided_parent(session: Session, item_id: uuid.UUID, owner_id: uuid.UUID) -> None:
    """FTY-321 boundary precheck: ``404`` when the item's parent event is voided.

    Runs before the estimator capability is invoked, so a voided target is refused
    at the backend-core boundary and the capability (which is void-agnostic) never
    loads it. A missing or cross-user item passes through — the capability's own
    owner-scoped loader reports those as ``404``.
    """

    try:
        ensure_parent_event_not_voided(session, CandidateType.FOOD, item_id, owner_id)
    except DerivedItemNotFound as exc:
        raise _NOT_FOUND from exc


@router.post(
    "/{user_id}/derived-items/food/{item_id}/exact-upgrade/apply",
    response_model=DerivedFoodItemDTO,
)
def apply_exact_evidence(
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: ExactEvidenceApplyRequest,
    current_user: CurrentUser,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
) -> DerivedFoodItemDTO:
    """Apply a server-signed exact-evidence proposal to the caller's own food item.

    Rewrites the item's source in place from the verified proposal and returns the
    updated item DTO (its new ``source`` descriptor and ``is_edited = false`` visible
    through the existing read model). Cross-user or unknown items — and items whose
    parent log event is voided — fail closed as ``404``; a proposal reference that is
    tampered, expired, or not held for this user + item returns ``422
    proposal_not_resolvable``; an uncostable amount returns ``422 amount_required``.
    """

    _refuse_voided_parent(session, item_id, user_id)
    settings: Settings = request.app.state.settings
    capability = build_exact_evidence_apply_capability(
        session, settings.auth_secret.get_secret_value()
    )
    try:
        item = capability.apply(
            owner_id=user_id,
            current_user=current_user,
            item_id=item_id,
            proposal_ref=payload.proposal_ref,
            amount=payload.amount,
        )
    except (ItemForbidden, ItemNotFound) as exc:
        raise _NOT_FOUND from exc
    except ProposalNotResolvable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "proposal_not_resolvable"},
        ) from exc
    except AmountNotCostable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "amount_required"},
        ) from exc

    return item_read_model.serialize_food_item(session, item)


@router.post(
    "/{user_id}/derived-items/food/{item_id}/exact-upgrade/barcode",
    response_model=ExactEvidenceProposalDTO,
)
def propose_barcode_evidence(
    user_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: BarcodeProposalRequest,
    current_user: CurrentUser,
    request: Request,
    session: Annotated[Session, Depends(get_session)],
    generator: Annotated[BarcodeProposalGenerator, Depends(get_barcode_proposal_generator)],
) -> ExactEvidenceProposalDTO:
    """Build an exact-or-fallback barcode proposal for the caller's own food item.

    Resolves the barcode through the hardened, cache-first Open Food Facts path and
    returns a server-signed **proposal** the user previews and applies via FTY-307 — a
    read-only operation that never mutates the item. A confident OFF match yields an
    ``exact`` ``product_database`` proposal costed at the item's current amount (or a
    proposal requiring an amount when the current amount is uncostable); no usable exact
    match yields a clearly-labelled ``fallback`` proposal from the item's identity when
    the estimator can produce one, else a ``none`` (no-proposal) response with a
    content-free reason.

    Cross-user / unknown / non-food items — and items whose parent log event is voided —
    fail closed as ``404``; an already-source-backed (ineligible) item returns ``422
    {"error": "not_upgradeable"}``; a transient/terminal OFF source failure surfaces a
    retryable ``503`` rather than a disguised miss. Nothing mutates on any path.
    """

    _refuse_voided_parent(session, item_id, user_id)
    settings: Settings = request.app.state.settings
    try:
        return barcode_proposal_service.propose_barcode_evidence(
            session,
            owner_id=user_id,
            current_user=current_user,
            item_id=item_id,
            barcode=payload.barcode,
            secret=settings.auth_secret.get_secret_value(),
            generator=generator,
        )
    except (ItemForbidden, ItemNotFound) as exc:
        raise _NOT_FOUND from exc
    except NotUpgradeable as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": "not_upgradeable"},
        ) from exc
    except (OffTransientError, OffResponseError) as exc:
        # A source outage during propose is surfaced honestly as retryable, never
        # disguised as a `none`/`fallback` miss (mirrors the re-match listing posture).
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"error": "source_unavailable"},
        ) from exc
