"""Synchronous label-upload processing seam (FTY-064).

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
"""

from __future__ import annotations

import uuid
from typing import Protocol

from fastapi import Request
from sqlalchemy.orm import Session

from app.estimator.label_step import LabelInput
from app.estimator.processing import process_estimation


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

    Delegates to :func:`process_estimation`, which selects the label pipeline when
    a ``label_upload`` is supplied, applies discard-by-default retention (FTY-077),
    and advances the event to its terminal status — all in the caller's session.

    ``max_attempts=1`` forces a single attempt: the image lives only in this
    request and is never enqueued, so there is no scheduler to honor a retry. A
    transient (``retryable``) provider error must therefore resolve to terminal
    ``failed`` here rather than leaving the event stuck in ``processing`` with a
    ``should_retry`` nothing will ever act on. The client can retry by uploading
    again.
    """

    process_estimation(
        session,
        log_event_id=log_event_id,
        user_id=user_id,
        label_upload=label_upload,
        max_attempts=1,
    )


def get_label_processor(request: Request) -> LabelProcessor:
    """FastAPI dependency returning the app's active label processor."""

    processor: LabelProcessor = request.app.state.label_processor
    return processor
