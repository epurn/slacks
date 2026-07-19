"""Synchronous label-upload processing seam (FTY-064, FTY-390).

The label upload endpoint resolves a captured nutrition-label image **in the
request**, not through the Celery broker: the estimation job payload carries only
ids (:mod:`app.estimator.enqueue`), and the raw image is discarded by default
(FTY-077), so it must never be persisted or published just to reach an async
worker. The image therefore only ever lives in the request that uploaded it and
is extracted there, through the same idempotent
:func:`app.estimator.processing.process_estimation` core the worker uses.

:class:`LabelProcessor` is a swappable seam, mirroring the enqueuer: production
wires :func:`synchronous_label_processor` (build the real vision provider and run
the label pipeline), while tests inject a double backed by a scripted provider so
the endpoint can be exercised without a live model. The active processor lives on
``app.state`` and is resolved per request by :func:`get_label_processor`.

**Never-reject on a transient provider blip (FTY-390).** A single label extraction
is one vision-provider call, and a *transient* (retryable) failure of that call is
infrastructure trouble, not "this isn't a label". Rejecting the user's good-faith
photo as a terminal ``failed`` event on such a blip is the same
infrastructure-rejects-good-faith-input sin the banh-mi incident showed, on the
label-photo path. So the seam retries a transiently-failed extraction a **bounded**
number of times with a short backoff, capped by an overall in-request **deadline**
(the endpoint stays synchronous — the mobile request must not hang). When even that
budget is exhausted it raises :class:`LabelExtractionUnavailable`; the route
(:func:`app.routers.log_events.upload_label_event`) discards everything this upload
created and returns a retryable ``503`` with **nothing persisted**, so the client —
which still holds the image locally — retries without littering the timeline with a
dead ``failed`` entry. Terminal ``failed`` stays reserved for genuinely-not-a-label
input (FTY-370). This mirrors the FTY-309 label exact-upgrade sibling route, which
already returns a retryable ``503`` on vision-provider failure.
"""

from __future__ import annotations

import time
import uuid
from typing import Protocol

from fastapi import Request
from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.estimator.label_step import LabelInput
from app.estimator.processing import process_estimation
from app.models.attachments import LogAttachment
from app.models.derived import DerivedFoodItem
from app.models.estimation import EstimationJob, EstimationRun
from app.models.food_sources import EvidenceSource
from app.models.log_events import LogEvent

#: Bounded in-request retry budget for a transient (retryable) vision-provider error
#: on the synchronous label path (FTY-390). One initial attempt plus retries, so a
#: brief provider blip is ridden out in-request while a permanently-down provider
#: costs exactly this many bounded calls per upload — the security-baseline
#: runaway/DoS guard (a permanently-broken provider cannot amplify beyond this small
#: documented budget). A documented tunable.
LABEL_MAX_ATTEMPTS = 3

#: Short backoff (seconds) between transient label retries. Deliberately brief: the
#: endpoint is synchronous and the mobile client is blocked on it, so a label
#: extraction (a single vision call) waits only a beat between attempts. A documented
#: tunable.
LABEL_RETRY_BACKOFF_SECONDS = 0.5

#: Overall in-request wall-clock deadline (seconds) across every attempt + backoff, so
#: a slow or repeatedly-failing provider can never hang the mobile request unboundedly.
#: When it is reached the seam stops retrying and raises
#: :class:`LabelExtractionUnavailable` exactly as attempt exhaustion does. A documented
#: tunable.
LABEL_REQUEST_DEADLINE_SECONDS = 20.0

#: Injectable clock seam (FTY-390): tests monkeypatch :data:`_sleep` to a no-op and, when
#: they exercise the deadline, :data:`_monotonic`, so the retry/backoff/deadline logic
#: runs without real wall-clock waits. Production uses the real monotonic clock + sleep.
_sleep = time.sleep
_monotonic = time.monotonic


class LabelExtractionUnavailable(Exception):
    """The synchronous label extraction failed transiently through the whole budget.

    Raised by :func:`synchronous_label_processor` when a *transient* (retryable)
    vision-provider error exhausts the in-request attempt budget or the request
    deadline (FTY-390). The route renders it as a retryable ``503`` and discards
    every row the upload created, so nothing is persisted and the client retries.
    Carries no image bytes, extracted text, or provider detail — the message is
    content-free.
    """


class LabelProcessor(Protocol):
    """Resolves a freshly created label event from its uploaded image, in-process."""

    def __call__(
        self,
        session: Session,
        *,
        log_event_id: uuid.UUID,
        user_id: uuid.UUID,
        label_upload: LabelInput,
    ) -> None: ...


def synchronous_label_processor(
    session: Session,
    *,
    log_event_id: uuid.UUID,
    user_id: uuid.UUID,
    label_upload: LabelInput,
) -> None:
    """Run the FTY-061 label-extraction pipeline for ``log_event_id`` in-request.

    Delegates to :func:`process_estimation` (which selects the label pipeline when a
    ``label_upload`` is supplied, applies discard-by-default retention (FTY-077), and
    advances the event to its terminal status — all in the caller's session), retrying
    a **transient** (retryable) provider failure up to :data:`LABEL_MAX_ATTEMPTS`
    attempts with a :data:`LABEL_RETRY_BACKOFF_SECONDS` backoff, bounded by the
    :data:`LABEL_REQUEST_DEADLINE_SECONDS` in-request deadline.

    A completed / needs-clarification / genuinely-not-a-label outcome returns normally
    (the route reads the terminal event). A transient failure that exhausts the attempt
    budget or the deadline raises :class:`LabelExtractionUnavailable` so the route
    discards the event and returns a retryable ``503`` — the image lives only in this
    request and is never enqueued, so there is no scheduler to honour a retry (FTY-390).
    """

    deadline = _monotonic() + LABEL_REQUEST_DEADLINE_SECONDS
    while True:
        result = process_estimation(
            session,
            log_event_id=log_event_id,
            user_id=user_id,
            label_upload=label_upload,
            max_attempts=LABEL_MAX_ATTEMPTS,
            synchronous_label=True,
        )
        if result.transient_exhausted:
            # Ran out of the bounded attempt budget on a transient provider error.
            raise LabelExtractionUnavailable("label extraction transiently unavailable")
        if not result.should_retry:
            # A terminal outcome (completed / needs_clarification / genuinely failed).
            return
        # A transient failure with attempts remaining: back off and retry, unless the
        # in-request deadline would be exceeded — never hang the mobile request.
        if _monotonic() + LABEL_RETRY_BACKOFF_SECONDS >= deadline:
            raise LabelExtractionUnavailable("label extraction deadline exceeded")
        _sleep(LABEL_RETRY_BACKOFF_SECONDS)


#: Event-scoped rows a synchronous label upload can create, ordered child-before-parent
#: so the delete cascade is explicit and engine-agnostic (Postgres enforces the FK
#: ``ON DELETE CASCADE``; the SQLite test engine does not, so we never rely on it).
_LABEL_EVENT_CHILDREN = (
    EvidenceSource,
    DerivedFoodItem,
    LogAttachment,
    EstimationRun,
    EstimationJob,
)


def purge_label_extraction(session: Session, log_event_id: uuid.UUID) -> None:
    """Delete every row a synchronous label upload created for ``log_event_id`` (FTY-390).

    Called when the in-request transient-retry budget is exhausted: the request returns
    a retryable ``503`` and must leave **nothing** behind — no log event,
    ``derived_food_items``, ``evidence_sources``, or ``log_attachments`` row — so a
    client retry creates at most one event on eventual success and the timeline is never
    littered with a dead ``failed`` entry (``label-upload.md``).

    A transient-exhausted run persisted only the event, its estimation job, and the
    per-attempt runs: a failed extraction persists no derived data (the step failed
    closed) and, even on ``save=true``, retains no image (retention short-circuits on a
    failed outcome). The derived/evidence/attachment deletes are therefore defensive and
    ordinarily no-ops; they keep the guarantee robust against drift and match the
    contract's "nothing persisted" wording exactly.
    """

    for model in _LABEL_EVENT_CHILDREN:
        session.execute(delete(model).where(model.log_event_id == log_event_id))
    session.execute(delete(LogEvent).where(LogEvent.id == log_event_id))
    session.commit()


def get_label_processor(request: Request) -> LabelProcessor:
    """FastAPI dependency returning the app's active label processor."""

    processor: LabelProcessor = request.app.state.label_processor
    return processor
