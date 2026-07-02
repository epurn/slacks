"""Log-event routes: create, list-today, and get-by-id (FTY-030, FTY-040).

The ``{user_id}`` path is explicit so object-level ownership is checked on every
access. A caller may only create, list, and read their own events; the service
fails closed on a mismatch and this router renders that as ``404`` so other
users' events are not even confirmed to exist. Raw text is never logged.

FTY-040 extends the create path: once a ``pending`` event is committed, an
estimation job is enqueued (through the swappable enqueuer seam) so the worker
picks it up asynchronously.

FTY-096 makes create safe-to-retry for an offline outbox: an optional opaque
``idempotency_key`` dedups a submit per user. A fresh keyed (or unkeyed) create
returns ``201`` and enqueues one job; a replay of an already-submitted key
returns ``200`` with the existing event at its current status and enqueues
nothing. See ``docs/contracts/log-events.md``.

FTY-064 adds the nutrition-label upload path: a captured label image is posted as
the raw request body and resolved synchronously in-request (the raw image is
discarded by default and never enqueued, so it cannot reach the broker). See
``docs/contracts/label-upload.md``.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.db import get_session
from app.deps import CurrentUser
from app.estimator.enqueue import EstimationEnqueuer, get_enqueuer
from app.estimator.label_step import LabelInput
from app.estimator.label_upload import LabelProcessor, get_label_processor
from app.schemas.corrections import DerivedFoodItemDTO
from app.schemas.label_proposal import LabelProposalConfirmRequest, LabelProposalResponse
from app.schemas.log_events import (
    ClarificationAnswerRequest,
    ClarificationQuestionDTO,
    ClarificationResponse,
    LogEventCreateRequest,
    LogEventDTO,
)
from app.services import clarification as clarification_service
from app.services import item_read_model
from app.services import label_proposal as label_proposal_service
from app.services import log_events as log_event_service
from app.services.attachments import (
    AttachmentInvalidContentType,
    AttachmentTooLarge,
    validate_upload,
)
from app.services.clarification import (
    ClarificationQuestionNotFound,
    NotAwaitingClarification,
)
from app.services.corrections import InvalidCorrection
from app.services.label_proposal import LabelProposalNotFound
from app.services.log_events import LogEventForbidden, LogEventNotFound

router = APIRouter(prefix="/api/users", tags=["log-events"])

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="log event not found")

#: The non-sensitive raw-text marker stored on a label-capture event. A label
#: upload carries no natural-language text, so this fixed, content-free string
#: stands in for the timeline; the food facts come from the extracted panel.
LABEL_EVENT_RAW_TEXT = "Nutrition label photo"


async def _read_image_body(request: Request) -> bytes:
    """Read the raw uploaded image bytes off the request body.

    Reading the body is async; the path operation that consumes these bytes is a
    sync function (so its blocking extraction runs in the threadpool), so the read
    is isolated in this dependency.
    """

    return await request.body()


@router.post(
    "/{user_id}/log-events",
    response_model=LogEventDTO,
    status_code=status.HTTP_201_CREATED,
)
def create_log_event(
    user_id: uuid.UUID,
    payload: LogEventCreateRequest,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    enqueue: Annotated[EstimationEnqueuer, Depends(get_enqueuer)],
    response: Response,
) -> LogEventDTO:
    """Create a ``pending`` log event and enqueue its estimation job.

    The event is committed first; only then is the job published, so the worker
    never races ahead of a persisted event. The payload carries ids only — never
    the raw text.

    With an ``idempotency_key`` the submit is safe to retry (FTY-096): a fresh
    create returns ``201`` and enqueues one job; an idempotent replay returns
    ``200`` with the existing event at its current status and enqueues nothing.
    """

    try:
        event, created = log_event_service.create_event(
            session,
            user_id,
            current_user,
            payload.raw_text,
            idempotency_key=payload.idempotency_key,
        )
    except LogEventForbidden as exc:
        raise _NOT_FOUND from exc
    if created:
        enqueue(log_event_id=event.id, user_id=event.user_id)
    else:
        response.status_code = status.HTTP_200_OK
    return LogEventDTO.model_validate(event)


@router.post(
    "/{user_id}/log-events/label",
    response_model=LogEventDTO,
    status_code=status.HTTP_201_CREATED,
)
def upload_label_event(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    data: Annotated[bytes, Depends(_read_image_body)],
    process_label: Annotated[LabelProcessor, Depends(get_label_processor)],
    content_type: Annotated[str | None, Header()] = None,
    save: Annotated[
        bool,
        Query(description="Retain the raw image as a log_attachment (FTY-077). Defaults to off."),
    ] = False,
) -> LogEventDTO:
    """Create a label event from an uploaded image and extract it in-request (FTY-064).

    The image is the raw request body; its declared type is the ``Content-Type``
    header. It is validated as **data** (size, content-type allowlist, magic-number
    signature) at the trust boundary before any work — an invalid upload fails
    closed with ``413``/``415`` and no event is created. A valid upload creates a
    ``pending`` event, then the FTY-061 label pipeline resolves it synchronously:
    the raw image only ever lives in this request (it is never enqueued), and is
    retained as a ``log_attachment`` only when ``save`` is set, discarded by
    default. Returns the event at its post-extraction status. Errors carry only an
    HTTP status — never image bytes or extracted content.
    """

    try:
        canonical_type = validate_upload(data, content_type or "")
    except AttachmentTooLarge as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="image exceeds the maximum upload size",
        ) from exc
    except AttachmentInvalidContentType as exc:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="upload is not an allowed image type",
        ) from exc

    try:
        # A label upload carries no idempotency key, so this always creates.
        event, _created = log_event_service.create_event(
            session, user_id, current_user, LABEL_EVENT_RAW_TEXT
        )
    except LogEventForbidden as exc:
        raise _NOT_FOUND from exc

    label = LabelInput(data=data, content_type=canonical_type, save=save)
    process_label(session, log_event_id=event.id, user_id=event.user_id, label_upload=label)
    session.refresh(event)
    return LogEventDTO.model_validate(event)


@router.get("/{user_id}/log-events", response_model=list[LogEventDTO])
def list_log_events(
    user_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    day: Annotated[
        date | None,
        Query(description="Calendar day (YYYY-MM-DD) in the user's timezone; defaults to today."),
    ] = None,
) -> list[LogEventDTO]:
    """List the caller's own events for ``day`` (their local timezone)."""

    try:
        events = log_event_service.list_events_for_day(session, user_id, current_user, day)
    except LogEventForbidden as exc:
        raise _NOT_FOUND from exc
    return [LogEventDTO.model_validate(event) for event in events]


@router.get("/{user_id}/log-events/{event_id}", response_model=LogEventDTO)
def get_log_event(
    user_id: uuid.UUID,
    event_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> LogEventDTO:
    """Return one of the caller's own events by id, or ``404`` otherwise."""

    try:
        event = log_event_service.get_event(session, user_id, current_user, event_id)
    except (LogEventForbidden, LogEventNotFound) as exc:
        raise _NOT_FOUND from exc
    return LogEventDTO.model_validate(event)


@router.get(
    "/{user_id}/log-events/{event_id}/clarification",
    response_model=ClarificationResponse,
)
def get_log_event_clarification(
    user_id: uuid.UUID,
    event_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> ClarificationResponse:
    """Return the open clarification questions for one of the caller's events.

    The mobile clarify sheet (FTY-153) fetches this lazily when it opens, so the
    Today list/poll DTO stays lean. Questions are ordered by ``position`` and
    carry their stable ``id`` (the key an answer submission references), their
    ``text``, and their quick-pick ``options`` (empty until the estimator
    persists options — FTY-172; the client then shows free-text only).

    The read is status-gated (``log-events.md`` v4): only a
    ``needs_clarification`` event serves questions, and only its **unanswered**
    ones, so a served question is always freshly answerable. Ownership is
    fail-closed (FTY-030): a cross-user or nonexistent ``event_id`` is
    indistinguishable as ``404`` (no existence oracle); a wrong-status event and
    one with no rows both return an empty list (no status oracle). The question
    text, like raw text, is never logged.
    """

    try:
        questions = log_event_service.list_clarification_questions(
            session, user_id, current_user, event_id
        )
    except (LogEventForbidden, LogEventNotFound) as exc:
        raise _NOT_FOUND from exc
    return ClarificationResponse(
        questions=[ClarificationQuestionDTO(id=q.id, text=q.question_text) for q in questions]
    )


@router.post(
    "/{user_id}/log-events/{event_id}/clarification/answers",
    response_model=LogEventDTO,
    status_code=status.HTTP_201_CREATED,
)
def answer_log_event_clarification(
    user_id: uuid.UUID,
    event_id: uuid.UUID,
    payload: ClarificationAnswerRequest,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    enqueue: Annotated[EstimationEnqueuer, Depends(get_enqueuer)],
    response: Response,
) -> LogEventDTO:
    """Resolve one clarification question on the caller's own event (FTY-171).

    The answer — a tapped quick-pick option's value or free text — is applied as
    a structured detail to the **same** event, which is re-estimated with every
    detail answered so far (``needs_clarification → processing``; the client
    polls as usual). The raw phrase is never mutated and no second event is ever
    created (audit findings A3/A5); an empty/whitespace answer is rejected
    ``422`` at the request boundary before any work.

    A fresh resolve returns ``201`` and enqueues the re-estimate only after the
    answer, the re-opened job, and the transition are committed — the worker
    never races an unpersisted resolve. An idempotent replay of an
    already-answered question returns ``200`` with the event's current DTO and
    enqueues nothing. A fresh answer for an event that has since moved on
    returns ``409 {"error": "not_awaiting_clarification"}`` and mutates nothing.
    Ownership fails closed (``404``, no existence oracle) for a cross-user or
    nonexistent event or a question that is not the event's own. The answer
    text, like raw text, is never logged.
    """

    try:
        event, resolved = clarification_service.answer_clarification_question(
            session,
            user_id,
            current_user,
            event_id,
            question_id=payload.question_id,
            answer_text=payload.answer,
        )
    except (LogEventForbidden, LogEventNotFound, ClarificationQuestionNotFound) as exc:
        raise _NOT_FOUND from exc
    except NotAwaitingClarification as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": "not_awaiting_clarification"},
        ) from exc
    if resolved:
        enqueue(log_event_id=event.id, user_id=event.user_id)
    else:
        response.status_code = status.HTTP_200_OK
    return LogEventDTO.model_validate(event)


@router.get(
    "/{user_id}/log-events/{event_id}/label-proposal",
    response_model=LabelProposalResponse,
)
def get_label_proposal(
    user_id: uuid.UUID,
    event_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
) -> LabelProposalResponse:
    """Return the uncounted proposed values for a label event (FTY-196).

    A legible label parse lands as an **uncounted proposal** (a ``proposed`` food
    item that does not count toward totals) rather than a counted ``resolved`` item,
    because "OCR is fallible — Fatty never silently trusts a fallible parse". This
    read backs the mobile confirm sheet (FTY-197): it returns the parsed food values
    plus their ``user_label`` ``source`` descriptor.

    Ownership is fail-closed (FTY-030): a cross-user or nonexistent ``event_id`` is
    indistinguishable as ``404`` (no existence oracle). An event with no proposal
    (never had one, or already confirmed) returns ``200`` with ``proposal: null``
    (no status oracle). The nutrition values, like ``raw_text``, are never logged.
    """

    try:
        item = label_proposal_service.get_label_proposal(session, user_id, current_user, event_id)
    except (LogEventForbidden, LogEventNotFound) as exc:
        raise _NOT_FOUND from exc
    proposal = item_read_model.serialize_food_item(session, item) if item is not None else None
    return LabelProposalResponse(proposal=proposal)


@router.post(
    "/{user_id}/log-events/{event_id}/label-proposal/confirm",
    response_model=DerivedFoodItemDTO,
)
def confirm_label_proposal(
    user_id: uuid.UUID,
    event_id: uuid.UUID,
    current_user: CurrentUser,
    session: Annotated[Session, Depends(get_session)],
    payload: LabelProposalConfirmRequest | None = None,
) -> DerivedFoodItemDTO:
    """Confirm a label proposal so it counts toward the day's totals (FTY-196).

    Flips the proposed food item ``proposed → resolved`` in one transaction, so the
    daily-summary finalized-state filter (unchanged) then counts it. An optional
    body carries adjusted values: a changed ``calories``/macro commits as the user's
    number (a ``user_edit`` value override — the item reads ``is_edited``), an
    adjusted ``amount`` (serving count) commits as a provenance-preserving rescale,
    and an omitted body commits the parsed values as-is. The ``user_label``
    provenance is preserved either way.

    Ownership is fail-closed (``404`` cross-user / nonexistent, no existence oracle,
    also when the owned event carries no proposal). A **double confirm** is
    idempotent — the already-committed item is returned, never double-counted. An
    out-of-range / invalid adjusted value returns ``422`` with a machine-readable
    error shape that never echoes the value.
    """

    adjustments = payload or LabelProposalConfirmRequest()
    try:
        item = label_proposal_service.confirm_label_proposal(
            session,
            user_id,
            current_user,
            event_id,
            calories=adjustments.calories,
            protein_g=adjustments.protein_g,
            carbs_g=adjustments.carbs_g,
            fat_g=adjustments.fat_g,
            amount=adjustments.amount,
        )
    except (LogEventForbidden, LogEventNotFound, LabelProposalNotFound) as exc:
        raise _NOT_FOUND from exc
    except InvalidCorrection as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"error": exc.code, "field": exc.field},
        ) from exc
    return item_read_model.serialize_food_item(session, item)
